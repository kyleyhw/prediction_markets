"""The operator's commands: `vp jobs` and `vp admin`.

They connect as the owner (`VP_MIGRATION_DATABASE_URL`), the credential
only the operator holds; the web and the workers never run them. What they
read of the job queue is its bookkeeping (kind, state, timings, error), not
any workspace's results. Every change of consequence (a halt, a pause, a
budget, a drain, an archive) is an entry in the audit chain naming the
operator.
"""

from __future__ import annotations

import getpass
import socket
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from vp.platform import audit
from vp.platform.principal import AuthMethod, Principal, Role

JOB_COLUMNS = (
    "id, kind, state, workspace_id, attempts, max_attempts, priority, created_at, "
    "started_at, finished_at, worker, progress, error"
)


def operator() -> Principal:
    """The operator at this terminal: attributable to the account running it."""
    return Principal(
        subject=f"operator:{getpass.getuser()}@{socket.gethostname()}",
        auth_method=AuthMethod.SYSTEM,
        roles=frozenset({Role.OPERATOR}),
    )


# ----------------------------------------------------------------- the queue


def list_jobs(
    conn: psycopg.Connection,
    *,
    state: str | None = None,
    kind: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    cur = conn.cursor(row_factory=dict_row)
    return cur.execute(
        "select id, kind, state, workspace_id, attempts, created_at, started_at, "
        "finished_at, left(error, 120) as error from jobs "
        "where (%(state)s::text is null or state = %(state)s) "
        "and (%(kind)s::text is null or kind = %(kind)s) "
        "order by created_at desc limit %(limit)s",
        {"state": state, "kind": kind, "limit": limit},
    ).fetchall()


def show_job(conn: psycopg.Connection, job_id: UUID) -> dict[str, Any] | None:
    cur = conn.cursor(row_factory=dict_row)
    return cur.execute(
        "select id, kind, state, workspace_id, attempts, max_attempts, priority, "
        "created_at, started_at, finished_at, worker, progress, payload, result, "
        "error, "
        "run_after, lease_until from jobs where id = %s",
        (job_id,),
    ).fetchone()


def retry_job(conn: psycopg.Connection, job_id: UUID) -> bool:
    """Put a dead, failed or cancelled job back on the queue with fresh attempts."""
    with conn.transaction():
        row = conn.execute(
            "update jobs set state = 'queued', attempts = 0, run_after = now(), "
            "error = null, finished_at = null, cancel_requested = false "
            "where id = %s and state in ('dead', 'failed', 'cancelled') returning kind",
            (job_id,),
        ).fetchone()
    if row:
        audit.append(
            conn, "job.retry", {"job": str(job_id), "kind": row[0]}, operator()
        )
    return row is not None


def set_drain(conn: psycopg.Connection, kind: str, drained: bool) -> None:
    """Stop (or resume) claiming one kind; jobs already running finish."""
    with conn.transaction():
        if drained:
            conn.execute(
                "insert into ops_flags (name, value) values (%s, 'true') "
                "on conflict (name) do update set set_at = now()",
                (f"drain:{kind}",),
            )
        else:
            conn.execute("delete from ops_flags where name = %s", (f"drain:{kind}",))
    audit.append(
        conn, "job.drain" if drained else "job.undrain", {"kind": kind}, operator()
    )


def queue_depth(conn: psycopg.Connection) -> list[tuple[str, str, int, float | None]]:
    """(kind, state, count, age of the oldest in seconds) for live jobs."""
    return conn.execute(
        "select kind, state, count(*), "
        "extract(epoch from now() - min(created_at))::float8 from jobs "
        "where state in ('queued', 'running', 'dead') group by 1, 2 order by 1, 2"
    ).fetchall()


# --------------------------------------------------------------------- halts


def halt(conn: psycopg.Connection, reason: str, workspace: UUID | None = None) -> UUID:
    """Halt the platform (no workspace) or pause one workspace."""
    who = operator()
    with conn.transaction():
        (halt_id,) = conn.execute(
            "insert into halts (scope, workspace_id, reason, set_by) "
            "values (%s, %s, %s, %s) returning id",
            (
                "workspace" if workspace else "platform",
                workspace,
                reason,
                who.subject,
            ),
        ).fetchone() or (None,)
    kind = "workspace.pause" if workspace else "platform.halt"
    data = {"halt": str(halt_id), "reason": reason, "workspace": workspace}
    audit.append(conn, kind, data, who)
    assert halt_id is not None
    return halt_id


def resume(conn: psycopg.Connection, workspace: UUID | None = None) -> int:
    """Clear the platform halt, or one workspace's pause; returns how many."""
    who = operator()
    with conn.transaction():
        cleared = conn.execute(
            "update halts set cleared_at = now(), cleared_by = %s "
            "where cleared_at is null and scope = %s "
            "and workspace_id is not distinct from %s returning id",
            (who.subject, "workspace" if workspace else "platform", workspace),
        ).fetchall()
    kind = "workspace.resume" if workspace else "platform.resume"
    audit.append(conn, kind, {"workspace": workspace, "cleared": len(cleared)}, who)
    return len(cleared)


def active_halts(conn: psycopg.Connection) -> list[dict[str, Any]]:
    cur = conn.cursor(row_factory=dict_row)
    return cur.execute(
        "select id, scope, workspace_id, reason, set_by, set_at from halts "
        "where cleared_at is null order by set_at"
    ).fetchall()


# ------------------------------------------------------------ budgets, costs


def set_budget(conn: psycopg.Connection, workspace: UUID, usd: Decimal) -> None:
    with conn.transaction():
        conn.execute(
            "insert into budgets (workspace_id, monthly_limit_usd) values (%s, %s) "
            "on conflict (workspace_id) do update set "
            "monthly_limit_usd = excluded.monthly_limit_usd, updated_at = now()",
            (workspace, usd),
        )
    audit.append(
        conn,
        "budget.set",
        {"workspace": workspace, "monthly_limit_usd": str(usd)},
        operator(),
    )


def costs(conn: psycopg.Connection, month: date | None = None) -> list[tuple[Any, ...]]:
    """(workspace, forecaster, domain, model, charged dollars) for a month."""
    start = (month or datetime.now(tz=UTC).date()).replace(day=1)
    return conn.execute(
        "select workspace_id, forecaster, domain, model, sum(usd) from spend "
        "where kind = 'charge' and at >= %s "
        "and at < (%s::date + interval '1 month') group by 1, 2, 3, 4 order by 5 desc",
        (start, start),
    ).fetchall()


def refresh(
    conn: psycopg.Connection, domain: str, kinds: tuple[str, ...]
) -> list[UUID]:
    """Queue an immediate data refresh for a domain: a dataset and/or a capture."""
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    ids = []
    for kind in kinds:
        # A dataset refresh does what the domain's daily build does.
        scheduled = conn.execute(
            "select payload from schedules where workspace_id is null and name = %s",
            (f"{kind}-{domain}",),
        ).fetchone()
        payload = scheduled[0] if scheduled else {"domain": domain}
        row = conn.execute(
            "select vp_jobs_enqueue_platform(%s, %s, %s, 50, now())",
            (kind, Jsonb(payload), f"admin:{kind}:{domain}:{stamp}"),
        ).fetchone()
        if row and row[0]:
            ids.append(row[0])
    audit.append(
        conn, "data.refresh", {"domain": domain, "kinds": list(kinds)}, operator()
    )
    return ids
