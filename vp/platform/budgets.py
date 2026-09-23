"""Monthly spending limits on paid model calls, per workspace.

The platform pays for language-model forecasts, so each workspace has a
monthly limit (proposed default $5, set by the operator). A job that may
spend is estimated before it is queued, the estimate is reserved against
the limit, and when it finishes the reservation is released and what was
actually spent is charged, one row per forecaster, domain and model with
its token counts. Statistical forecasters cost nothing and never reserve.

Rows live in `spend` (migration 0004) under row-level security: a
workspace sees only its own. The month is the calendar month in UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.observe import SPEND_USD
from vp.platform.principal import Principal

DEFAULT_LIMIT_USD = Decimal("5")


class OverBudget(Exception):
    """The estimate does not fit in what is left of this month's limit."""


@dataclass(frozen=True)
class Standing:
    """A workspace's month so far."""

    limit_usd: Decimal
    charged_usd: Decimal
    reserved_usd: Decimal

    @property
    def remaining_usd(self) -> Decimal:
        return max(self.limit_usd - self.charged_usd - self.reserved_usd, Decimal(0))


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(tz=UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def standing(pool: ConnectionPool, principal: Principal) -> Standing:
    """The limit, what has been charged and what is reserved this month."""
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute("select monthly_limit_usd from budgets").fetchone()
        sums = conn.execute(
            "select coalesce(sum(usd) filter (where kind = 'charge'), 0), "
            "coalesce(sum(usd) filter (where kind in ('reservation', 'release')), 0) "
            "from spend where at >= %s and paid_by = 'platform'",
            (_month_start(),),
        ).fetchone()
    charged, reserved = sums if sums else (Decimal(0), Decimal(0))
    return Standing(
        limit_usd=row[0] if row else DEFAULT_LIMIT_USD,
        charged_usd=Decimal(charged),
        reserved_usd=Decimal(reserved),
    )


def reserve(pool: ConnectionPool, principal: Principal, usd: float) -> None:
    """Check an estimate against the month and hold it, or raise OverBudget.

    The check and the hold are one transaction under a lock on the
    workspace, so two runs started together cannot both fit in the last
    dollar. The hold is tied to the job when the job exists (`attach`).
    """
    if usd <= 0:
        return
    amount = Decimal(str(round(usd, 6)))
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"budget:{principal.workspace}",),
        )
        row = conn.execute("select monthly_limit_usd from budgets").fetchone()
        limit = row[0] if row else DEFAULT_LIMIT_USD
        (used,) = conn.execute(
            "select coalesce(sum(usd), 0) from spend "
            "where at >= %s and paid_by = 'platform'",
            (_month_start(),),
        ).fetchone() or (Decimal(0),)
        if Decimal(used) + amount > limit:
            raise OverBudget(
                f"this run is estimated at ${amount:.2f}, and "
                f"${max(limit - Decimal(used), 0):.2f} "
                f"of this month's ${limit:.2f} is left"
            )
        conn.execute(
            "insert into spend (workspace_id, kind, usd) "
            "values (%s, 'reservation', %s)",
            (principal.workspace, amount),
        )


def settle_job(
    pool: ConnectionPool,
    principal: Principal,
    job_id: UUID,
    reserved_usd: float,
    charges: list[dict[str, Any]],
    paid_by: str = "platform",
) -> Decimal:
    """Release a job's reservation and charge what it actually spent.

    Args:
        charges: one dict per forecaster, domain and model, with `usd` and
            optionally `forecaster`, `domain`, `model` and the token counts.

    Returns:
        The total charged.
    """
    total = Decimal(0)
    with pool.connection() as conn, tenant_session(conn, principal):
        if reserved_usd > 0:
            conn.execute(
                "insert into spend (workspace_id, job_id, kind, usd) "
                "values (%s, %s, 'release', %s)",
                (principal.workspace, job_id, -Decimal(str(round(reserved_usd, 6)))),
            )
        for c in charges:
            usd = Decimal(str(round(float(c.get("usd", 0)), 6)))
            if usd <= 0 and not c.get("input_tokens"):
                continue
            conn.execute(
                "insert into spend (workspace_id, job_id, kind, forecaster, domain, "
                "model, input_tokens, output_tokens, cache_read_tokens, "
                "cache_write_tokens, usd, paid_by) "
                "values (%s, %s, 'charge', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    principal.workspace,
                    job_id,
                    c.get("forecaster"),
                    c.get("domain"),
                    c.get("model"),
                    int(c.get("input_tokens", 0)),
                    int(c.get("output_tokens", 0)),
                    int(c.get("cache_read_tokens", 0)),
                    int(c.get("cache_write_tokens", 0)),
                    usd,
                    paid_by,
                ),
            )
            total += usd
            if paid_by == "platform":
                SPEND_USD.labels(c.get("forecaster") or "unknown").inc(float(usd))
    return total


def breakdown(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    """This month's charges by forecaster, domain and model."""
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select forecaster, domain, model, count(*), sum(input_tokens), "
            "sum(output_tokens), sum(cache_read_tokens), sum(usd), paid_by from spend "
            "where kind = 'charge' and at >= %s group by 1, 2, 3, 9 order by 8 desc",
            (_month_start(),),
        ).fetchall()
    keys = (
        "forecaster",
        "domain",
        "model",
        "rows",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "usd",
        "paid_by",
    )
    return [dict(zip(keys, r, strict=True)) for r in rows]
