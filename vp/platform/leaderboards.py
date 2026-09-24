"""Opt-in leaderboards by skill against the market (plan, task 84;
docs/collaboration.md).

The `leaderboard` platform job reads the settled paper positions of
opted-in strategies only (`vp_leaderboard_rows`) and, for each board (a
domain or all of them, over 30 days, 90 days or all time), scores each
strategy by the paired Brier difference against the market's price with a
bootstrap interval. Only strategies with at least `MIN_RANKED` settled
positions are ranked, by the mean advantage; the rest are listed with their
count. P&L is shown beside skill, never alone and never as the rank.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import numpy as np
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.principal import Principal
from vp.platform.teams import NotAllowed, record
from vp.strategy.card import paired_interval

MIN_RANKED = 50
WINDOWS = {"30d": 30, "90d": 90, "all": None}


def opt_in(
    pool: ConnectionPool, principal: Principal, strategy_id: UUID, display_name: str
) -> None:
    if not principal.may_write:
        raise NotAllowed("viewers cannot enter a strategy")
    name = display_name.strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("a display name is 1 to 60 characters")
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "insert into leaderboard_optins (strategy_id, display_name) "
            "values (%s, %s) on conflict (strategy_id) do update set "
            "display_name = excluded.display_name",
            (strategy_id, name),
        )
        record(conn, "leaderboard_joined", "strategy", strategy_id, {"as": name})


def opt_out(pool: ConnectionPool, principal: Principal, strategy_id: UUID) -> bool:
    if not principal.may_write:
        raise NotAllowed("viewers cannot withdraw a strategy")
    with pool.connection() as conn, tenant_session(conn, principal):
        cur = conn.execute(
            "delete from leaderboard_optins where strategy_id = %s", (strategy_id,)
        )
        if cur.rowcount:
            record(conn, "leaderboard_left", "strategy", strategy_id)
    return bool(cur.rowcount)


def entered(
    pool: ConnectionPool, principal: Principal, strategy_id: UUID
) -> str | None:
    """The name a strategy is entered under, or None."""
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select display_name from leaderboard_optins where strategy_id = %s",
            (strategy_id,),
        ).fetchone()
    return row[0] if row else None


def entry(rows: list[tuple[float, float, float]]) -> dict[str, Any]:
    """One strategy on one board, from its (brier, brier_market, pnl) rows."""
    n = len(rows)
    brier = np.array([r[0] for r in rows])
    market = np.array([r[1] for r in rows])
    diffs = market - brier
    interval = paired_interval(diffs) if n >= 2 else None
    return {
        "settled": n,
        "ranked": n >= MIN_RANKED,
        "skill": float(1 - brier.mean() / market.mean()) if market.mean() else None,
        "advantage": None
        if interval is None
        else {"mean": interval[0], "low": interval[1], "high": interval[2]},
        "pnl": round(float(sum(r[2] for r in rows)), 2),
    }


def compute(
    rows: list[tuple[Any, ...]], now: datetime | None = None
) -> dict[str, dict[str, Any]]:
    """Every board from (strategy, name, domain, at, brier, market, pnl) rows."""
    now = now or datetime.now(tz=UTC)
    names: dict[str, str] = {}
    grouped: dict[tuple[str, str], list[tuple[float, float, float]]] = defaultdict(list)
    for sid, name, domain, at, brier, market, pnl in rows:
        names[str(sid)] = name
        for window, days in WINDOWS.items():
            if days is not None and at < now - timedelta(days=days):
                continue
            for board_domain in {"all", domain or "all"}:
                grouped[(f"{board_domain}:{window}", str(sid))].append(
                    (brier, market, pnl or 0.0)
                )
    boards: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (board, sid), data in grouped.items():
        boards[board].append({"strategy_id": sid, "name": names[sid], **entry(data)})
    out = {}
    for board, entries in boards.items():
        ranked = sorted(
            (e for e in entries if e["ranked"] and e["advantage"]),
            key=lambda e: -e["advantage"]["mean"],
        )
        for i, e in enumerate(ranked, 1):
            e["rank"] = i
        rest = sorted(
            (e for e in entries if "rank" not in e), key=lambda e: -e["settled"]
        )
        out[board] = {
            "entries": ranked + rest,
            "min_ranked": MIN_RANKED,
            "computed_at": now.isoformat(timespec="seconds"),
        }
    return out


def run(ctx: Any) -> dict[str, Any]:
    """The `leaderboard` platform job."""
    with ctx.pool.connection() as conn:
        rows = conn.execute("select * from vp_leaderboard_rows()").fetchall()
        boards = compute(rows)
        with conn.transaction():
            conn.execute("delete from leaderboards")
            for board, body in boards.items():
                conn.execute(
                    "insert into leaderboards (board, body) values (%s, %s)",
                    (board, Jsonb(body)),
                )
    return {"boards": len(boards), "settlements": len(rows)}


def read(pool: ConnectionPool) -> dict[str, Any]:
    with pool.connection() as conn:
        rows = conn.execute(
            "select board, body from leaderboards order by board"
        ).fetchall()
    return {board: body for board, body in rows}
