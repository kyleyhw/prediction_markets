"""Signals and the benchmark on the platform (plan, Phase 16).

Three platform jobs, run as the system on the shared data:

* `signal_bench`: the bench of every domain (`vp.signals.bench`), kept as
  the latest result per domain for the Signals page.
* `benchmark_freeze`: once a week, the question set from the newest
  captures (seeded by the week's name, so anyone can redraw it) and every
  platform configuration's forecasts on it, sealed: the market's price at
  freezing and each signal that answers. Only the commitments are shown.
* `benchmark_score`: daily, the labels of the week's questions from the
  venue's own settlement records; when every question has settled, or
  three days after the last scheduled end, each entry is revealed, checked
  against its commitment and scored.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.domains import DOMAINS
from vp.forecast.evidence import Evidence, parse_time
from vp.markets.store import read_markets
from vp.platform.jobs import JobContext
from vp.signals import benchmark, registry
from vp.signals.bench import bench

GRACE = timedelta(days=3)


def signal_bench(ctx: JobContext) -> dict[str, Any]:
    svc = ctx.services
    done = {}
    domains = (
        [ctx.job.payload["domain"]] if ctx.job.payload.get("domain") else list(DOMAINS)
    )
    for i, domain in enumerate(domains):
        ctx.progress(i / len(domains), f"benching {domain}")
        svc.refresh([domain])
        with tempfile.TemporaryDirectory(dir=svc.work_dir) as tmp:
            root = svc.shared.workroot(Path(tmp))
            if not (root / "markets" / domain / "resolved.parquet").exists():
                continue
            result = bench(root, domain)
        with svc.pool.connection() as conn:
            conn.execute(
                "insert into signal_bench (domain, result) values (%s, %s) "
                "on conflict (domain) do update set result = excluded.result, "
                "created_at = now()",
                (domain, Jsonb(result)),
            )
        done[domain] = {k: v["verdict"] for k, v in result["signals"].items()}
    return done


def _seed(week: str) -> int:
    return int.from_bytes(hashlib.sha256(week.encode()).digest()[:4], "big")


def benchmark_freeze(ctx: JobContext, now: datetime | None = None) -> dict[str, Any]:
    svc = ctx.services
    now = now or datetime.now(tz=UTC)
    week = benchmark.week_of(now)
    with svc.pool.connection() as conn:
        if conn.execute(
            "select 1 from benchmark_weeks where week = %s", (week,)
        ).fetchone():
            return {"week": week, "skipped": "already frozen"}
    svc.refresh(list(DOMAINS))
    markets = []
    for domain in DOMAINS:
        snaps = sorted((svc.shared.root / "snapshots" / domain).glob("*.parquet"))
        if snaps:
            markets += read_markets(snaps[-1])
    body = benchmark.freeze(markets, now=now, seed=_seed(week))
    if not body["questions"]:
        return {"week": week, "skipped": "no eligible markets"}
    by_id = {m.market_id: m for m in markets}
    configs: dict[str, dict[str, float]] = {
        "market": {q["market_id"]: q["price"] for q in body["questions"]}
    }
    with tempfile.TemporaryDirectory(dir=svc.work_dir) as tmp:
        root = svc.shared.workroot(Path(tmp))
        evidence = Evidence(now, root, live=markets)
        for signal_id in registry.ids():
            signal = registry.load(signal_id)
            answers = {}
            for q in body["questions"]:
                m = by_id[q["market_id"]]
                if signal.meta.applies(m):
                    p = signal.compute(m, evidence)
                    if p is not None:
                        answers[q["market_id"]] = p
            if answers:
                configs[f"signal:{signal_id}"] = answers
    with svc.pool.connection() as conn, conn.transaction():
        (week_id,) = conn.execute(
            "insert into benchmark_weeks (week, body, hash, frozen_at) "
            "values (%s, %s, %s, %s) returning id",
            (week, Jsonb(body), body["hash"], now),
        ).fetchone()
        for config, answers in configs.items():
            sealed = benchmark.commit(body["hash"], config, answers)
            conn.execute(
                "insert into benchmark_entries (week_id, config, commitment, salt, "
                "payload) values (%s, %s, %s, %s, %s)",
                (
                    week_id,
                    config,
                    sealed["commitment"],
                    sealed["salt"],
                    sealed["payload"],
                ),
            )
    return {"week": week, "questions": len(body["questions"]), "configs": len(configs)}


def benchmark_score(ctx: JobContext, now: datetime | None = None) -> dict[str, Any]:
    from vp.platform.handlers import ResolvedFirst

    svc = ctx.services
    now = now or datetime.now(tz=UTC)
    with svc.pool.connection() as conn:
        weeks = conn.execute(
            "select id, week, body from benchmark_weeks where scored_at is null"
        ).fetchall()
    lookup = ResolvedFirst(svc.pool, svc.source())
    out = {}
    for week_id, week, body in weeks:
        labels = {}
        for q in body["questions"]:
            try:
                market = lookup.market(q["condition_id"])
            except Exception:  # noqa: BLE001 - try again tomorrow
                continue
            if (
                market.resolution_state == "resolved"
                and market.resolved_outcome is not None
            ):
                labels[q["market_id"]] = market.resolved_outcome
        ends = [parse_time(q["end_date"]) for q in body["questions"]]
        last = max((e for e in ends if e is not None), default=now)
        if len(labels) < len(body["questions"]) and now < last + GRACE:
            out[week] = {"settled": len(labels), "of": len(body["questions"])}
            continue
        with svc.pool.connection() as conn, conn.transaction():
            entries = conn.execute(
                "select config, commitment, salt, payload from benchmark_entries "
                "where week_id = %s",
                (week_id,),
            ).fetchall()
            for config, commitment, salt, payload in entries:
                if not benchmark.verify(commitment, salt, payload):
                    raise RuntimeError(
                        f"{week} {config}: entry does not match its commitment"
                    )
                conn.execute(
                    "update benchmark_entries set revealed_at = %s, score = %s "
                    "where week_id = %s and config = %s",
                    (
                        now,
                        Jsonb(benchmark.score(body, payload, labels)),
                        week_id,
                        config,
                    ),
                )
            conn.execute(
                "update benchmark_weeks set scored_at = %s where id = %s",
                (now, week_id),
            )
        out[week] = {"revealed": len(entries), "settled": len(labels)}
    return out


# ------------------------------------------------------------------- reads


def latest_bench(pool: ConnectionPool) -> dict[str, Any]:
    with pool.connection() as conn:
        rows = conn.execute(
            "select domain, result, created_at from signal_bench"
        ).fetchall()
    return {d: r | {"created_at": c.isoformat()} for d, r, c in rows}


def weeks(pool: ConnectionPool, limit: int = 12) -> list[dict[str, Any]]:
    """Recent weeks with their entries; salts and forecasts only once revealed."""
    with pool.connection() as conn:
        rows = conn.execute(
            "select id, week, body, hash, frozen_at, scored_at from benchmark_weeks "
            "order by frozen_at desc limit %s",
            (limit,),
        ).fetchall()
        out = []
        for week_id, week, body, digest, frozen, scored in rows:
            entries = conn.execute(
                "select config, commitment, salt, payload, revealed_at, score "
                "from benchmark_entries where week_id = %s order by config",
                (week_id,),
            ).fetchall()
            out.append(
                {
                    "week": week,
                    "hash": digest,
                    "seed": body["seed"],
                    "frozen_at": frozen.isoformat(),
                    "scored_at": scored.isoformat() if scored else None,
                    "questions": body["questions"],
                    "entries": [
                        {
                            "config": config,
                            "commitment": commitment,
                            **(
                                {
                                    "salt": salt,
                                    "forecasts": json.loads(payload)["forecasts"],
                                    "score": score,
                                }
                                if revealed
                                else {}
                            ),
                        }
                        for (
                            config,
                            commitment,
                            salt,
                            payload,
                            revealed,
                            score,
                        ) in entries
                    ],
                }
            )
    return out
