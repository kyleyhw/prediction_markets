"""Risk, strategy health and promotion on the platform (docs/portfolio.md,
Phase 20).

The exposure of a workspace's paper accounts, the health check that runs
after each settlement (a decayed strategy is paused, its owners told, and
`strategy.health` emitted), and the promotion protocol: six criteria, each
with its evidence and an audit row, and a person's approval.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.markets.schema import BinaryMarket
from vp.markets.store import read_markets
from vp.paper.loop import replay
from vp.platform import audit, notify, webhooks
from vp.platform.db import tenant_session
from vp.platform.ledger import PgLedger
from vp.platform.principal import Principal
from vp.platform.teams import NotAllowed, record
from vp.portfolio import exposure, health
from vp.portfolio.exposure import Position
from vp.strategy.card import paired_interval

# The mandate (criterion 6) and the forward and health criteria (3, 5).
MAX_WORST_SHARE, MAX_EVENT_SHARE = 0.20, 0.10
FORWARD_MIN, HEALTHY_DAYS, P_POSITIVE = 100, 28, 0.95
WEEK = timedelta(days=7)


def _time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def latest_markets(root: Path, domains: set[str]) -> dict[str, BinaryMarket]:
    """The newest snapshot's markets of each domain, by market id."""
    out: dict[str, BinaryMarket] = {}
    for d in domains:
        snaps = sorted((root / "snapshots" / d).glob("*.parquet"))
        if snaps:
            out.update({m.market_id: m for m in read_markets(snaps[-1]) if m.market_id})
    return out


def _accounts(conn: Any, version: UUID | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select a.id, a.name, a.initial_cash, v.strategy_id, s.name "
        "from paper_accounts a left join strategy_versions v "
        "on v.id = a.strategy_version_id "
        "left join strategies s on s.id = v.strategy_id "
        + ("where a.strategy_version_id = %s" if version else ""),
        (version,) if version else (),
    ).fetchall()
    return [
        {"id": i, "name": n, "cash": float(c), "strategy_id": sid, "strategy": sn}
        for i, n, c, sid, sn in rows
    ]


def positions(
    pool: ConnectionPool,
    principal: Principal,
    root: Path,
    version: UUID | None = None,
    store: Any = None,
) -> tuple[list[Position], float]:
    """Every open paper position of the workspace (or of one version), priced
    at the latest snapshot, and the accounts' bankrolls."""
    with pool.connection() as conn, tenant_session(conn, principal):
        accounts = _accounts(conn, version)
    held: list[tuple[dict[str, Any], dict[str, Any]]] = []
    bankroll = 0.0
    for a in accounts:
        books = replay(PgLedger(pool, principal, a["id"], store=store), a["cash"])
        for book in books.values():
            bankroll += book.bankroll
            held += [(a, o) for o in book.open.values()]
    markets = latest_markets(root, {str(o.get("domain")) for _, o in held})
    out = []
    for a, o in held:
        m = markets.get(o["market_id"])
        p = m.p_yes if m is not None and m.p_yes is not None else o.get("q")
        out.append(
            Position(
                market_id=o["market_id"],
                event_id=o.get("event_id"),
                side=o["side"],
                shares=float(o["shares"]),
                stake=float(o["stake"]),
                p_first=float(p if p is not None else 0.5),
                domain=o.get("domain"),
                end=_time(m.end_date if m is not None else o.get("end_date")),
                neg_risk=bool(m.neg_risk if m is not None else o.get("neg_risk")),
                strategy=a["strategy"] or a["name"],
            )
        )
    return out, bankroll


def risk(
    pool: ConnectionPool, principal: Principal, root: Path, store: Any = None
) -> dict[str, Any]:
    """The risk x-ray: the whole book, and the part settling this week."""
    held, bankroll = positions(pool, principal, root, store=store)
    now = datetime.now(tz=UTC)
    week = [p for p in held if p.end is not None and p.end <= now + WEEK]
    return {
        "all": exposure.report(held, bankroll or None),
        "week": exposure.report(week, bankroll or None),
        "bankroll": round(bankroll, 2),
    }


# ----------------------------------------------------------------- health


def _advantages(conn: Any, strategy: UUID) -> tuple[list[float], list[str]]:
    rows = conn.execute(
        "select (e.entry -> 'data' ->> 'brier_market')::float - "
        "(e.entry -> 'data' ->> 'brier')::float, e.at "
        "from ledger_entries e join paper_accounts a on a.id = e.account_id "
        "join strategy_versions v on v.id = a.strategy_version_id "
        "where v.strategy_id = %s and e.kind = 'settlement' "
        "and e.entry -> 'data' ->> 'brier_market' is not null "
        "and e.entry -> 'data' ->> 'forecaster' <> 'market' "
        "order by e.at, e.seq",
        (strategy,),
    ).fetchall()
    return [float(d) for d, _ in rows], [at.isoformat() for _, at in rows]


def check_health(pool: ConnectionPool, principal: Principal, strategy: UUID) -> dict:
    """Evaluate a strategy's health; act on a change of state."""
    with pool.connection() as conn, tenant_session(conn, principal):
        d, times = _advantages(conn, strategy)
        report = health.evaluate(d, times)
        before = conn.execute(
            "select state, paused_at from strategy_health where strategy_id = %s",
            (strategy,),
        ).fetchone()
        was = before[0] if before else "too_early"
        state = report["state"]
        paused = before[1] if before else None
        if state == "decayed" and was != "decayed":
            paused = datetime.now(tz=UTC)
        conn.execute(
            "insert into strategy_health (strategy_id, state, settled, cusum, report, "
            "paused_at) values (%s, %s, %s, %s, %s, %s) on conflict (strategy_id) do "
            "update set state = excluded.state, settled = excluded.settled, "
            "cusum = excluded.cusum, report = excluded.report, "
            "paused_at = excluded.paused_at, updated_at = now()",
            (
                strategy,
                state,
                report["settled"],
                report["cusum"],
                Jsonb(report),
                paused,
            ),
        )
        # Tell people of trouble, and of recovery from it.
        if state != was and (
            state in ("watch", "decayed")
            or (state == "healthy" and was in ("watch", "decayed"))
        ):
            name = conn.execute(
                "select name from strategies where id = %s", (strategy,)
            ).fetchone()
            title = f"{name[0] if name else 'A strategy'} is now {state}"
            body = (
                "It has been paused in paper; resume it from its page."
                if state == "decayed"
                else f"CUSUM {report['cusum']} of {health.H} after "
                f"{report['settled']} settled."
            )
            notify.notify(
                conn,
                notify.members(conn),
                "health",
                title,
                body,
                f"#strategy/{strategy}",
            )
            webhooks.emit(
                conn,
                "strategy.health",
                {"strategy_id": str(strategy), "from": was, "to": state},
            )
            record(conn, "health_" + state, "strategy", strategy, {"from": was})
    return report


def get_health(
    pool: ConnectionPool, principal: Principal, strategy: UUID
) -> dict | None:
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select state, report, paused_at, updated_at from strategy_health "
            "where strategy_id = %s",
            (strategy,),
        ).fetchone()
    if row is None:
        return None
    state, report, paused, at = row
    return {
        **report,
        "state": state,
        "paused": paused is not None,
        "updated_at": at.isoformat(),
    }


def resume(pool: ConnectionPool, principal: Principal, strategy: UUID) -> bool:
    if not principal.may_write:
        raise NotAllowed("viewers cannot resume a strategy")
    with pool.connection() as conn, tenant_session(conn, principal):
        cur = conn.execute(
            "update strategy_health set paused_at = null, resumed_at = now(), "
            "resumed_by = vp_current_user_id() where strategy_id = %s "
            "and paused_at is not null",
            (strategy,),
        )
        if cur.rowcount:
            record(conn, "resumed", "strategy", strategy)
    return bool(cur.rowcount)


def paused(pool: ConnectionPool, principal: Principal, version: UUID) -> bool:
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select h.paused_at from strategy_health h join strategy_versions v "
            "on v.strategy_id = h.strategy_id where v.id = %s",
            (version,),
        ).fetchone()
    return bool(row and row[0])


# -------------------------------------------------------------- promotion


def _criterion(n: int, name: str, ok: bool, detail: str, evidence: dict) -> dict:
    return {"n": n, "name": name, "passed": ok, "detail": detail, "evidence": evidence}


def evaluate(
    pool: ConnectionPool,
    principal: Principal,
    version: UUID,
    target: str,
    root: Path,
    store: Any = None,
) -> dict[str, Any]:
    """Evaluate the criteria for moving a version to ``target``."""
    if target not in ("paper", "live"):
        raise ValueError("a target is paper or live")
    with pool.connection() as conn, tenant_session(conn, principal):
        v = conn.execute(
            "select strategy_id from strategy_versions where id = %s", (version,)
        ).fetchone()
        if v is None:
            raise LookupError("no such strategy version")
        strategy = v[0]
        run = conn.execute(
            "select id, results -> 'card' from runs where strategy_version_id = %s "
            "and results ? 'card' order by created_at desc limit 1",
            (version,),
        ).fetchone()
        accounts = _accounts(conn, version)
        d = [
            float(x)
            for (x,) in conn.execute(
                "select (e.entry -> 'data' ->> 'brier_market')::float - "
                "(e.entry -> 'data' ->> 'brier')::float from ledger_entries e "
                "join paper_accounts a on a.id = e.account_id "
                "where a.strategy_version_id = %s and e.kind = 'settlement' "
                "and e.entry -> 'data' ->> 'brier_market' is not null "
                "and e.entry -> 'data' ->> 'forecaster' <> 'market'",
                (version,),
            ).fetchall()
        ]
        leak = conn.execute(
            "select id, result from jobs where kind = 'leakage' "
            "and state = 'succeeded' and payload ->> 'account_id' = any(%s) "
            "order by finished_at desc limit 1",
            ([str(a["id"]) for a in accounts],),
        ).fetchone()
        h = conn.execute(
            "select state, report from strategy_health where strategy_id = %s",
            (strategy,),
        ).fetchone()
    card = run[1] if run else None
    ev_run = {"run_id": str(run[0])} if run else {}
    crit = []
    scored, needed = (card or {}).get("scored", 0), (card or {}).get("needed_n")
    crit.append(
        _criterion(
            1,
            "enough_markets",
            bool(card) and needed is not None and scored >= needed,
            f"scored {scored}, needed {needed}" if card else "no backtest yet",
            ev_run,
        )
    )
    adv = (card or {}).get("advantage") or {}
    p_pos = (card or {}).get("p_positive")
    ok2 = p_pos >= P_POSITIVE if p_pos is not None else bool(adv) and adv["low"] > 0
    crit.append(
        _criterion(
            2,
            "backtest_skill",
            bool(card) and ok2,
            f"P(advantage > 0) = {p_pos:.3f}"
            if p_pos is not None
            else "from the interval",
            ev_run,
        )
    )
    if target == "live":
        iv = paired_interval(np.array(d)) if len(d) >= 2 else None
        ok3 = iv is not None and (iv[1] > 0 or (len(d) >= FORWARD_MIN and iv[0] > 0))
        crit.append(
            _criterion(
                3,
                "forward_skill",
                ok3,
                f"{len(d)} settled; advantage {iv[0]:+.4f} [{iv[1]:+.4f}, {iv[2]:+.4f}]"
                if iv
                else f"{len(d)} settled",
                {"accounts": [str(a["id"]) for a in accounts]},
            )
        )
        crit.append(
            _criterion(
                4,
                "no_leakage",
                bool(leak and (leak[1] or {}).get("passed")),
                "passed"
                if leak and (leak[1] or {}).get("passed")
                else "no passing check",
                {"job_id": str(leak[0])} if leak else {},
            )
        )
        since = None
        if h and h[0] == "healthy":
            last = [t for t in h[1].get("transitions", []) if t["to"] == "healthy"]
            since = _time(last[-1]["at"]) if last and last[-1].get("at") else None
        weeks_ok = since is not None and datetime.now(tz=UTC) - since >= timedelta(
            days=HEALTHY_DAYS
        )
        crit.append(
            _criterion(
                5,
                "healthy",
                weeks_ok,
                f"{h[0]} since {since.date().isoformat()}"
                if h and since
                else (h[0] if h else "not checked yet"),
                {"strategy_id": str(strategy)},
            )
        )
        held, bankroll = positions(pool, principal, root, version, store)
        rep = exposure.report(held, bankroll or None)
        worst = -rep.get("worst_case", 0.0)
        top = max((g["stake"] for g in rep.get("by_event", [])), default=0.0)
        ok6 = bankroll > 0 and worst <= MAX_WORST_SHARE * bankroll
        ok6 = ok6 and top <= MAX_EVENT_SHARE * bankroll
        crit.append(
            _criterion(
                6,
                "mandate",
                ok6,
                f"worst case {worst:.2f} of {bankroll:.2f}; largest event {top:.2f}",
                {"positions": len(held)},
            )
        )
    passed = all(c["passed"] for c in crit)
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "insert into promotion_evaluations (strategy_version_id, target, criteria, "
            "passed) values (%s, %s, %s, %s) returning id, evaluated_at",
            (version, target, Jsonb(crit), passed),
        ).fetchone()
        assert row is not None
        for c in crit:
            audit.append(
                conn,
                "promotion.criterion",
                {"evaluation_id": str(row[0]), "version_id": str(version), **c},
                principal,
            )
    return {
        "id": str(row[0]),
        "target": target,
        "passed": passed,
        "criteria": crit,
        "binding": target == "live",
        "evaluated_at": row[1].isoformat(),
    }


def evaluations(pool: ConnectionPool, principal: Principal, strategy: UUID) -> list:
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select e.id, v.version, e.target, e.criteria, e.passed, e.evaluated_at, "
            "e.approved_at from promotion_evaluations e join strategy_versions v "
            "on v.id = e.strategy_version_id where v.strategy_id = %s "
            "order by e.evaluated_at desc limit 20",
            (strategy,),
        ).fetchall()
    return [
        {
            "id": str(i),
            "version": ver,
            "target": t,
            "criteria": c,
            "passed": p,
            "evaluated_at": at.isoformat(),
            "approved_at": ap.isoformat() if ap else None,
        }
        for i, ver, t, c, p, at, ap in rows
    ]


def approve(pool: ConnectionPool, principal: Principal, evaluation: UUID) -> None:
    """A person approves a passing evaluation; nothing else can."""
    if not principal.may_write:
        raise NotAllowed("viewers cannot approve a promotion")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update promotion_evaluations set approved_by = vp_current_user_id(), "
            "approved_at = now() where id = %s and passed and approved_at is null "
            "returning strategy_version_id, target",
            (evaluation,),
        ).fetchone()
        if row is None:
            raise ValueError(
                "only a passing evaluation, not yet approved, can be approved"
            )
        audit.append(
            conn,
            "promotion.decision",
            {
                "evaluation_id": str(evaluation),
                "version_id": str(row[0]),
                "target": row[1],
            },
            principal,
        )
        record(conn, "promoted", "strategy_version", row[0], {"target": row[1]})
