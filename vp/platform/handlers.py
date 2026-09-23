"""What each kind of job does.

Every handler runs the engine unchanged over a data root assembled from
the shared cache (`SharedRoot.workroot`) and writes what it produced to
the workspace's tables and the object store, as the job's principal:

* `backtest`: `vp.backtest.run.run_backtest`; the run's results and
  summary go to `runs`, its files to `workspaces/<id>/runs/<run>/`.
* `paper_cycle`: `vp.paper.loop.run_cycle` for each of the account's
  domains, against the newest shared snapshot (the market-data service
  takes those; a cycle never polls the venue), writing to the account's
  `PgLedger`; its forecasts go to `forecasts`.
* `settle`: `vp.paper.loop.settle`, asking the venue only about markets the
  resolutions table already says have resolved.
* `leakage`: `vp.paper.leakage` between a backtest run and an account.

and for the platform, as `system`:

* `dataset`: a domain's resolved dataset, published as a new version, with
  any price histories not yet stored;
* `snapshot`: one capture of a domain's open markets (the market-data
  service writes these on its schedule; this is the fallback and the
  on-demand refresh);
* `partitions`, `sweep`: maintenance.

Statistical forecasts are memoised in `forecast_memo`: the same forecaster
on the same market with the same inputs gives the same answer, so a second
workspace asking gets the first one's result without recomputing it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.backtest.run import BacktestConfig, run_backtest
from vp.domains import DOMAINS
from vp.forecast import Evidence, Forecaster, make_forecaster
from vp.forecast.base import Forecast
from vp.markets.polymarket import PolymarketSource
from vp.markets.schema import BinaryMarket, utc_now_iso
from vp.markets.snapshot import collect_snapshot
from vp.paper import leakage
from vp.paper.loop import run_cycle, settle
from vp.platform import budgets, llmops
from vp.platform.config import Settings
from vp.platform.db import tenant_session
from vp.platform.jobs import Handler, JobContext, run_scheduler
from vp.platform.ledger import PgLedger
from vp.platform.principal import Principal
from vp.platform.sample import ensure_sample_account, sample_principal
from vp.platform.storage import (
    SHARED,
    ObjectStore,
    SharedRoot,
    publish_dataset,
)

logger = logging.getLogger(__name__)

#: Bumped when a statistical forecaster's method changes, so old memos stop
#: matching.
MEMO_VERSION = "1"
#: Forecasters whose answers are private (a person's prompt) or paid.
UNMEMOISED = frozenset({"llm"})


@dataclass
class Services:
    """What handlers need from the process: settings, database, storage."""

    settings: Settings
    pool: ConnectionPool
    store: ObjectStore
    shared: SharedRoot
    source: Callable[[], PolymarketSource] = PolymarketSource
    notify: Callable[[str, str], None] | None = None
    work_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))

    def refresh(self, domains: Sequence[str]) -> None:
        self.shared.refresh(domains)


# ---------------------------------------------------------------- memoising


class Memoised:
    """A statistical forecaster whose answers are shared through `forecast_memo`."""

    def __init__(self, inner: Forecaster, pool: ConnectionPool, salt: str) -> None:
        self.inner = inner
        self.pool = pool
        self.salt = salt
        self.hits = 0

    @property
    def name(self) -> str:
        return self.inner.name

    def key(self, market: BinaryMarket, evidence: Evidence) -> str:
        parts = [
            MEMO_VERSION,
            self.name,
            self.salt,
            market.market_id,
            evidence.cutoff.isoformat(),
        ]
        return hashlib.sha256(json.dumps(parts).encode()).hexdigest()

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        key = self.key(market, evidence)
        with self.pool.connection() as conn:
            row = conn.execute(
                "select record from forecast_memo where memo_key = %s", (key,)
            ).fetchone()
        if row is not None:
            self.hits += 1
            record = row[0]
            return None if record.get("declined") else Forecast(**record)
        answer = self.inner.forecast(market, evidence)
        record = {"declined": True} if answer is None else asdict(answer)
        with self.pool.connection() as conn:
            conn.execute(
                "insert into forecast_memo (memo_key, forecaster, market_id, record) "
                "values (%s, %s, %s, %s) on conflict do nothing",
                (key, self.name, market.market_id, Jsonb(record)),
            )
        return answer


def forecasters_for(
    names: Sequence[str], domain: str, pool: ConnectionPool, salt: str, **llm: Any
) -> list[Forecaster]:
    out: list[Forecaster] = []
    for name in names:
        if name == "llm":
            out.append(make_forecaster(name, domain, **llm))
        else:
            out.append(Memoised(make_forecaster(name, domain), pool, salt))
    return out


def _captured_at(stem: str) -> datetime | None:
    """The time in a capture's name (20260923T120936Z), or None."""
    try:
        return datetime.strptime(stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _stamp() -> str:
    return utc_now_iso().replace("-", "").replace(":", "")


def _dataset_version(store: ObjectStore, domain: str) -> str:
    stamp = store.get_bytes(f"{SHARED}/markets/{domain}/LATEST")
    return stamp.decode().strip() if stamp else "none"


# ------------------------------------------------------------ workspace jobs


def backtest(ctx: JobContext) -> dict[str, Any]:
    svc: Services = ctx.services
    p = ctx.job.payload
    domain = str(p["domain"])
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain {domain!r}")
    config = BacktestConfig(
        domain=domain,
        forecasters=tuple(p.get("forecasters") or ("market", "constant")),
        hours_before_close=float(p.get("hours_before_close", 24.0)),
        kinds=tuple(p.get("kinds") or ()),
        max_markets=p.get("max_markets"),
        seed=int(p.get("seed", 0)),
        fee_rate=float(p.get("fee_rate", 0.0)),
        min_edge=float(p.get("min_edge", 0.0)),
    )
    ctx.progress(0.0, "getting the data")
    svc.refresh([domain])
    salt = _dataset_version(svc.store, domain)
    run_id = uuid4()
    with tempfile.TemporaryDirectory(dir=svc.work_dir) as tmp:
        root = svc.shared.workroot(Path(tmp) / "root")
        out = Path(tmp) / "out"
        llm: dict[str, Any] = {}
        paid_by = "platform"
        if "llm" in config.forecasters:
            client, paid_by = llmops.client_for(
                svc.pool,
                ctx.principal,
                svc.settings.anthropic_api_key,
                svc.settings.master_key,
            )
            llm = {"client": client, "batch": bool(p.get("batch", False))}
            if p.get("model"):
                llm["model"] = str(p["model"])
        forecasters = forecasters_for(config.forecasters, domain, svc.pool, salt, **llm)
        result = run_backtest(
            config,
            root,
            out,
            forecasters=forecasters,
            progress=lambda f, m: ctx.progress(0.05 + 0.9 * f, m),
        )
        ctx.progress(0.96, "saving the run")
        prefix = f"workspaces/{ctx.principal.workspace}/runs/{run_id}"
        for path in sorted(out.iterdir()):
            if path.is_file():
                svc.store.put_file(f"{prefix}/{path.name}", path)
        results = json.loads((out / "results.json").read_text())
        summary = (out / "summary.md").read_text()
    with svc.pool.connection() as conn, tenant_session(conn, ctx.principal):
        conn.execute(
            "insert into runs (id, workspace_id, kind, job_id, config, results, "
            "summary, artifacts, created_by) "
            "values (%s, %s, 'backtest', %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                ctx.principal.workspace,
                ctx.job.id,
                Jsonb(asdict(config)),
                Jsonb(results),
                summary,
                prefix,
                ctx.principal.user_id,
            ),
        )
    charges = []
    for f in forecasters:
        calls = getattr(f, "calls", None)
        if not calls:
            continue
        charges.append(
            {
                "forecaster": f.name,
                "domain": domain,
                "model": getattr(f, "model", None),
                "input_tokens": sum(c["input_tokens"] for c in calls),
                "output_tokens": sum(c["output_tokens"] for c in calls),
                "cache_read_tokens": sum(c.get("cache_read_tokens", 0) for c in calls),
                "cache_write_tokens": sum(
                    c.get("cache_write_tokens", 0) for c in calls
                ),
                "usd": sum(c["cost_usd"] for c in calls),
            }
        )
    charged = budgets.settle_job(
        svc.pool, ctx.principal, ctx.job.id, ctx.job.reserved_usd, charges, paid_by
    )
    return {
        "run_id": str(run_id),
        "scored": result.common,
        "cost_usd": float(charged),
        "memo_hits": sum(getattr(f, "hits", 0) for f in forecasters),
    }


def _account(svc: Services, principal: Principal, account_id: UUID) -> dict[str, Any]:
    with svc.pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select id, domains, forecasters, initial_cash from paper_accounts "
            "where id = %s",
            (account_id,),
        ).fetchone()
    if row is None:
        raise ValueError("no such paper account in this workspace")
    return {
        "id": row[0],
        # `*` is every domain the engine has (the sample account's list).
        "domains": list(DOMAINS)
        if "*" in row[1]
        else [d for d in row[1] if d in DOMAINS],
        "forecasters": row[2],
        "cash": float(row[3]),
    }


def paper_cycle(ctx: JobContext) -> dict[str, Any]:
    account_id = UUID(str(ctx.job.payload["account_id"]))
    return _trade(ctx, ctx.principal, account_id)


def sample_cycle(ctx: JobContext) -> dict[str, Any]:
    """The platform's hourly cycle of the sample account everyone reads."""
    account_id = ensure_sample_account(ctx.pool)
    return _trade(ctx, sample_principal(), account_id)


def _trade(ctx: JobContext, principal: Principal, account_id: UUID) -> dict[str, Any]:
    svc: Services = ctx.services
    account = _account(svc, principal, account_id)
    ledger = PgLedger(svc.pool, principal, account["id"], store=svc.store)
    broken = ledger.verify()
    if broken is not None:
        raise RuntimeError(f"ledger chain broken at entry {broken}; refusing to trade")
    svc.refresh(account["domains"])
    counts: dict[str, Any] = {}
    domains = account["domains"]
    for i, domain in enumerate(domains):
        ctx.progress(i / max(len(domains), 1), f"trading {domain}")
        snaps = sorted((svc.shared.root / "snapshots" / domain).glob("*.parquet"))
        if not snaps:
            counts[domain] = {"skipped": "no capture of this domain yet"}
            continue
        with tempfile.TemporaryDirectory(dir=svc.work_dir) as tmp:
            root = svc.shared.workroot(Path(tmp))
            forecasters = forecasters_for(
                account["forecasters"], domain, svc.pool, snaps[-1].stem
            )
            # The information cutoff is the capture's time: what was known
            # when the prices traded against were seen, never later than now.
            # Every account trading this capture then asks the same question,
            # so the statistical forecasts are shared through the memo.
            # One transaction per domain's cycle. The cycle makes no network
            # call (it trades the capture), so the transaction stays short.
            with ledger.batch():
                counts[domain] = run_cycle(
                    DOMAINS[domain],
                    forecasters,
                    None,
                    root,
                    ledger,
                    initial_cash=account["cash"],
                    snapshot=root / "snapshots" / domain / snaps[-1].name,
                    now=_captured_at(snaps[-1].stem),
                )
            _store_forecasts(
                ctx,
                principal,
                root / "paper" / "forecasts.jsonl",
                domain,
                account["id"],
            )
    return {"account_id": str(account["id"]), "domains": counts}


def _store_forecasts(
    ctx: JobContext, principal: Principal, path: Path, domain: str, account_id: UUID
) -> None:
    if not path.exists():
        return
    svc: Services = ctx.services
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    with (
        svc.pool.connection() as conn,
        tenant_session(conn, principal),
        conn.cursor() as cur,
    ):
        cur.executemany(
            "insert into forecasts (workspace_id, account_id, job_id, forecaster, "
            "market_id, domain, p_hat, cutoff, cost_usd, record) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    principal.workspace,
                    account_id,
                    ctx.job.id,
                    r["forecaster"],
                    r.get("market_id"),
                    domain,
                    r["p_hat"],
                    r["cutoff"],
                    r.get("cost_usd", 0.0),
                    Jsonb(r),
                )
                for r in rows
            ],
        )


class ResolvedFirst:
    """Settlement's market lookup, asking the venue only when it must.

    A market the resolutions table (kept by the market-data service) does
    not list as resolved is still pending, and is reported so without a
    request. One it does list is fetched from the venue by condition id,
    because the label comes only from the venue's own settlement record
    (closed is not resolved). Once the venue's record says resolved it no
    longer changes, so it is kept in `settled_markets` and every other
    account holding the market reads it there instead of asking again.
    """

    def __init__(self, pool: ConnectionPool, source: PolymarketSource) -> None:
        self.pool = pool
        self.source = source
        self.asked = 0

    def market(self, identifier: str, *, depth: int = 0) -> BinaryMarket:
        with self.pool.connection() as conn:
            known = conn.execute(
                "select status from resolutions where condition_id = %s", (identifier,)
            ).fetchone()
            record = conn.execute(
                "select record from tracked_markets where condition_id = %s",
                (identifier,),
            ).fetchone()
        from vp.markets.store import market_from_row, market_to_row

        if (known is None or known[0] != "resolved") and record is not None:
            return market_from_row(record[0])
        with self.pool.connection() as conn:
            kept = conn.execute(
                "select record from settled_markets where condition_id = %s",
                (identifier,),
            ).fetchone()
        if kept is not None:
            return market_from_row(kept[0])
        self.asked += 1
        market = self.source.market(identifier, depth=depth)
        if market.resolution_state == "resolved":
            row = json.loads(json.dumps(market_to_row(market), default=str))
            with self.pool.connection() as conn:
                conn.execute(
                    "insert into settled_markets (condition_id, record) "
                    "values (%s, %s) on conflict do nothing",
                    (identifier, Jsonb(row)),
                )
        return market


def settle_account(ctx: JobContext) -> dict[str, Any]:
    account_id = UUID(str(ctx.job.payload["account_id"]))
    return _settle(ctx, ctx.principal, account_id)


def sample_settle(ctx: JobContext) -> dict[str, Any]:
    """The platform's hourly settlement of the sample account."""
    return _settle(ctx, sample_principal(), ensure_sample_account(ctx.pool))


def _settle(ctx: JobContext, principal: Principal, account_id: UUID) -> dict[str, Any]:
    svc: Services = ctx.services
    account = _account(svc, principal, account_id)
    ledger = PgLedger(svc.pool, principal, account["id"], store=svc.store)
    lookup = ResolvedFirst(svc.pool, svc.source())
    counts = settle(lookup, ledger, initial_cash=account["cash"])
    return {**counts, "venue_requests": lookup.asked}


def leakage_check(ctx: JobContext) -> dict[str, Any]:
    svc: Services = ctx.services
    p = ctx.job.payload
    account = _account(svc, ctx.principal, UUID(str(p["account_id"])))
    with svc.pool.connection() as conn, tenant_session(conn, ctx.principal):
        run = conn.execute(
            "select artifacts, config from runs where id = %s",
            (UUID(str(p["run_id"])),),
        ).fetchone()
    if run is None:
        raise ValueError("no such backtest run in this workspace")
    domain = run[1]["domain"]
    svc.refresh([domain])
    with tempfile.TemporaryDirectory(dir=svc.work_dir) as tmp:
        run_dir = Path(tmp) / "run"
        if not svc.store.download(
            f"{run[0]}/forecasts.jsonl", run_dir / "forecasts.jsonl"
        ):
            raise ValueError("the run's forecasts are missing from storage")
        rows = leakage.gaps(
            leakage.backtest_scores(run_dir, svc.shared.root, domain),
            leakage.forward_scores(PgLedger(svc.pool, ctx.principal, account["id"])),
        )
    return {
        "summary": leakage.summary(rows) if rows else "no forecaster settled in both"
    }


# ------------------------------------------------------------- platform jobs


def dataset(ctx: JobContext) -> dict[str, Any]:
    svc: Services = ctx.services
    domain = DOMAINS[str(ctx.job.payload["domain"])]
    from vp.markets.dataset import build_resolved_dataset

    prefix = f"{SHARED}/histories/{domain.name}/"
    stored = set(svc.store.keys(prefix))
    added = 0

    # Each history goes to the store as soon as it is written: a build cut
    # short by a restart keeps what it fetched, and its retry skips those.
    def keep(path: Path) -> None:
        nonlocal added
        svc.store.put_file(prefix + path.name, path)
        added += 1
        if added % 50 == 0:
            ctx.progress(0.5, f"{added} price histories fetched")

    with tempfile.TemporaryDirectory(dir=svc.work_dir) as tmp:
        root = Path(tmp)
        ctx.progress(0.0, "finding settled markets")
        report = build_resolved_dataset(
            domain,
            svc.source(),
            root,
            max_markets=ctx.job.payload.get("max_markets"),
            with_history=bool(ctx.job.payload.get("history", True)),
            history_limit=ctx.job.payload.get("history_limit"),
            have_history=frozenset(
                k.removeprefix(prefix).removesuffix(".parquet") for k in stored
            ),
            on_history=keep,
        )
        stamp = _stamp()
        publish_dataset(
            svc.store,
            domain.name,
            root / "markets" / domain.name / "resolved.parquet",
            stamp,
        )
    if svc.notify:
        svc.notify("vp_data", f"dataset:{domain.name}")
    return {"version": stamp, "histories_added": added, "summary": report.summary()}


def snapshot(ctx: JobContext) -> dict[str, Any]:
    svc: Services = ctx.services
    domain = DOMAINS[str(ctx.job.payload["domain"])]
    with tempfile.TemporaryDirectory(dir=svc.work_dir) as tmp:
        path, count = collect_snapshot(
            domain,
            svc.source(),
            Path(tmp),
            depth=int(ctx.job.payload.get("depth", 5)),
            max_markets=ctx.job.payload.get("max_markets"),
        )
        svc.store.put_file(f"{SHARED}/snapshots/{domain.name}/{path.name}", path)
    if svc.notify:
        svc.notify("vp_data", f"snapshot:{domain.name}")
    return {"markets": count, "stamp": path.stem}


def partitions(ctx: JobContext) -> dict[str, Any]:
    with ctx.pool.connection() as conn:
        (made,) = conn.execute("select vp_ensure_partitions(3)").fetchone() or (0,)
    return {"created": made}


def sweep(ctx: JobContext) -> dict[str, Any]:
    with ctx.pool.connection() as conn:
        row = conn.execute("select * from vp_platform_sweep()").fetchone()
    return dict(
        zip(("sign_in_tokens", "sessions", "jobs"), row or (0, 0, 0), strict=True)
    )


def handlers(extra: dict[str, Handler] | None = None) -> dict[str, Handler]:
    """Every kind this module handles, plus any given (the ingest's and the
    evidence collectors', which live with their services)."""
    table: dict[str, Handler] = {
        "backtest": backtest,
        "paper_cycle": paper_cycle,
        "settle": settle_account,
        "sample_cycle": sample_cycle,
        "sample_settle": sample_settle,
        "leakage": leakage_check,
        "dataset": dataset,
        "snapshot": snapshot,
        "partitions": partitions,
        "sweep": sweep,
        "scheduler": run_scheduler,
    }
    table.update(extra or {})
    return table
