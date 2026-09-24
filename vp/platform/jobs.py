"""Background jobs: a queue in Postgres, and the workers that run it.

A job is a row in `jobs` (migration 0004). The web enqueues a workspace's
jobs under its row-level security; the scheduler and the ingest service
enqueue the platform's own through `vp_jobs_enqueue_platform`. Workers
claim with `vp_jobs_claim`, which takes the next queued job of the kinds
they serve with `FOR UPDATE SKIP LOCKED`, so any number of workers share
one queue without two taking the same job, and which claims nothing while
the platform, the job's workspace, or its kind is halted or drained.

A claimed job carries a lease. The worker renews it from a heartbeat
thread and records progress with it; if the worker dies the lease runs out
and the scheduler's reaper puts the job back on the queue, or, once its
attempts are spent, in the dead state an operator inspects. Asking a job
to stop sets a flag the next heartbeat reads; the handler sees it as
`JobCancelled` at its next progress report.

A job runs as a `Principal` with the `job` method and the id of the
person who asked for it, in their workspace, so everything it reads and
writes passes the same row-level security as their own requests.
Platform jobs run as `system` and touch only the shared tables.

Workers wait for work on `LISTEN vp_jobs` (a trigger notifies on every
insert), with a slow poll behind it for jobs whose `run_after` arrives
later; a new job starts in milliseconds rather than on the next poll.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.observe import span
from vp.platform.principal import AuthMethod, Principal, Role

logger = logging.getLogger(__name__)

#: Kinds a person may start from the page or the API, in their workspace.
WORKSPACE_KINDS = frozenset(
    {
        "shadow_import",
        "backtest",
        "compile",
        "research",
        "paper_cycle",
        "settle",
        "leakage",
        "brief",
        "share_refresh",
    }
)
#: Kinds the platform runs for everyone.
PLATFORM_KINDS = frozenset(
    {
        "scheduler",
        "snapshot",
        "dataset",
        "evidence",
        "partitions",
        "reconcile",
        "sweep",
        "sample_cycle",
        "sample_settle",
        "signal_bench",
        "benchmark_freeze",
        "benchmark_score",
        "deliver",
        "leaderboard",
    }
)
#: Interactive work first, scheduled work next, maintenance last.
PRIORITY_INTERACTIVE, PRIORITY_SCHEDULED, PRIORITY_MAINTENANCE = 50, 100, 200


class JobCancelled(Exception):
    """Someone asked the running job to stop."""


class LeaseLost(Exception):
    """The job's lease expired and it was taken back; stop without finishing."""


@dataclass(frozen=True)
class Job:
    """One claimed job."""

    id: UUID
    kind: str
    workspace_id: UUID | None
    created_by: UUID | None
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    lease_token: UUID
    reserved_usd: float = 0.0
    waited_seconds: float = 0.0  # from when it could first run to its start

    @property
    def principal(self) -> Principal:
        """Who the job acts as: the person who asked, in their workspace."""
        if self.workspace_id is None:
            return Principal(subject="platform", auth_method=AuthMethod.SYSTEM)
        if self.created_by is None:
            # The person has since been removed; their workspace's work runs
            # on under the workspace's own name, and cannot write as them.
            return Principal(subject="orphaned", auth_method=AuthMethod.SYSTEM)
        return Principal(
            subject=str(self.created_by),
            auth_method=AuthMethod.JOB,
            workspace=self.workspace_id,
            roles=frozenset({Role.EDITOR}),
        )


# --------------------------------------------------------------- enqueueing


def enqueue(
    pool: ConnectionPool,
    principal: Principal,
    kind: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    priority: int = PRIORITY_INTERACTIVE,
    run_after: datetime | None = None,
    reserved_usd: float = 0.0,
) -> UUID:
    """Queue a job in the principal's workspace; returns its id.

    With an idempotency key, asking twice returns the first job rather than
    queueing a second.
    """
    if kind not in WORKSPACE_KINDS:
        raise ValueError(f"{kind} is not a job a workspace can start")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "insert into jobs (workspace_id, created_by, kind, payload, "
            "idempotency_key, priority, run_after, reserved_usd) "
            "values (%s, %s, %s, %s, %s, %s, coalesce(%s, now()), %s) "
            "on conflict do nothing returning id",
            (
                principal.workspace,
                principal.user_id,
                kind,
                Jsonb(payload),
                idempotency_key,
                priority,
                run_after,
                reserved_usd,
            ),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "select id from jobs where kind = %s and idempotency_key = %s",
                (kind, idempotency_key),
            ).fetchone()
    assert row is not None
    return row[0]


def enqueue_platform(
    pool: ConnectionPool,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
    priority: int = PRIORITY_MAINTENANCE,
    run_after: datetime | None = None,
) -> UUID | None:
    """Queue platform work; returns its id, or None if the key was taken."""
    with pool.connection() as conn:
        row = conn.execute(
            "select vp_jobs_enqueue_platform(%s, %s, %s, %s, %s)",
            (kind, Jsonb(payload or {}), idempotency_key, priority, run_after),
        ).fetchone()
    return row[0] if row else None


def workspace_jobs(
    pool: ConnectionPool, principal: Principal, *, limit: int = 50
) -> list[dict[str, Any]]:
    """The workspace's recent jobs, newest first."""
    with pool.connection() as conn, tenant_session(conn, principal):
        cur = conn.cursor(row_factory=dict_row)
        return cur.execute(
            "select id, kind, payload, state, progress, result, error, attempts, "
            "created_at, started_at, finished_at, reserved_usd, cancel_requested "
            "from jobs order by created_at desc limit %s",
            (limit,),
        ).fetchall()


def request_cancel(pool: ConnectionPool, principal: Principal, job_id: UUID) -> bool:
    """Ask a job to stop: a queued job is cancelled at once, a running one at
    its next heartbeat. Returns False for a job that is not this workspace's
    or has already finished."""
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update jobs set "
            "state = case when state = 'queued' then 'cancelled' else state end, "
            "finished_at = case when state = 'queued' then now() else finished_at end, "
            "cancel_requested = true "
            "where id = %s and state in ('queued', 'running') returning id",
            (job_id,),
        ).fetchone()
    return row is not None


# ------------------------------------------------------------------ running


class JobContext:
    """What a handler gets: the job, where to report progress, the services."""

    def __init__(
        self, job: Job, pool: ConnectionPool, services: Any, lease: int
    ) -> None:
        self.job = job
        self.pool = pool
        self.services = services
        self._lease = lease
        self._last_report = 0.0
        self._state = "ok"

    @property
    def principal(self) -> Principal:
        return self.job.principal

    def heartbeat(self, progress: dict[str, Any] | None = None) -> None:
        """Renew the lease; raise if the job was cancelled or taken back."""
        with self.pool.connection() as conn:
            row = conn.execute(
                "select vp_jobs_heartbeat(%s, %s, %s, %s)",
                (
                    self.job.id,
                    self.job.lease_token,
                    Jsonb(progress) if progress is not None else None,
                    self._lease,
                ),
            ).fetchone()
        self._state = row[0] if row else "lost"
        self.check()

    def check(self) -> None:
        if self._state == "cancel":
            raise JobCancelled()
        if self._state == "lost":
            raise LeaseLost()

    def progress(self, fraction: float, message: str = "") -> None:
        """Report how far the job has got; at most about once a second."""
        now = time.monotonic()
        if now - self._last_report < 1.0 and fraction < 1.0:
            self.check()
            return
        self._last_report = now
        self.heartbeat(
            {
                "fraction": round(min(max(fraction, 0.0), 1.0), 4),
                "message": message[:200],
            }
        )


Handler = Callable[[JobContext], dict[str, Any] | None]


@dataclass
class Worker:
    """Claims and runs jobs of some kinds, `concurrency` at a time."""

    pool: ConnectionPool
    handlers: dict[str, Handler]
    kinds: tuple[str, ...]
    services: Any = None
    concurrency: int = 1
    lease_seconds: int = 60
    poll_seconds: float = 5.0
    listen_url: str | None = None
    name: str = field(default_factory=lambda: f"{socket.gethostname()}:{id(object())}")
    on_job: Callable[[Job, str, float], None] | None = None

    def __post_init__(self) -> None:
        missing = set(self.kinds) - set(self.handlers)
        if missing:
            raise ValueError(f"no handler for: {', '.join(sorted(missing))}")
        self._wake = threading.Event()

    # -- claiming --

    def claim(self) -> Job | None:
        with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            row = cur.execute(
                "select * from vp_jobs_claim(%s, %s, %s)",
                (list(self.kinds), self.name, self.lease_seconds),
            ).fetchone()
        if row is None:
            return None
        return Job(
            id=row["id"],
            kind=row["kind"],
            workspace_id=row["workspace_id"],
            created_by=row["created_by"],
            payload=row["payload"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            lease_token=row["lease_token"],
            reserved_usd=float(row["reserved_usd"]),
            waited_seconds=max(
                0.0,
                (
                    row["started_at"] - max(row["run_after"], row["created_at"])
                ).total_seconds(),
            ),
        )

    def run_once(self) -> bool:
        """Claim and run one job; False when there was nothing to claim."""
        job = self.claim()
        if job is None:
            return False
        self.execute(job)
        return True

    def execute(self, job: Job) -> str:
        """Run a claimed job to its end and record the outcome."""
        ctx = JobContext(job, self.pool, self.services, self.lease_seconds)
        done = threading.Event()
        beat = threading.Thread(target=self._beat, args=(ctx, done), daemon=True)
        beat.start()
        started = time.monotonic()
        state, result, error = "succeeded", None, None
        try:
            with span("job", kind=job.kind, job=str(job.id)):
                result = self.handlers[job.kind](ctx) or {}
        except JobCancelled:
            state, error = "cancelled", "cancelled on request"
        except LeaseLost:
            done.set()
            logger.warning("job %s lost its lease; not recording an outcome", job.id)
            return "lost"
        except Exception as exc:  # noqa: BLE001 - recorded on the job, then retried
            logger.exception("job %s (%s) failed", job.id, job.kind)
            state, error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            done.set()
        with self.pool.connection() as conn:
            row = conn.execute(
                "select vp_jobs_finish(%s, %s, %s, %s, %s)",
                (job.id, job.lease_token, state, Jsonb(result), error),
            ).fetchone()
        outcome = row[0] if row else "lost"
        if self.on_job is not None:
            self.on_job(job, outcome, time.monotonic() - started)
        return outcome

    def _beat(self, ctx: JobContext, done: threading.Event) -> None:
        while not done.wait(self.lease_seconds / 3):
            try:
                ctx.heartbeat()
            except JobCancelled, LeaseLost:
                return  # the handler sees the same state at its next report
            except Exception:  # noqa: BLE001 - a missed beat is retried
                logger.exception("heartbeat failed for %s", ctx.job.id)

    # -- the loop --

    def run(self, stop: threading.Event) -> None:
        """Run until `stop` is set: a listener and `concurrency` runners."""
        threads = [threading.Thread(target=self._listen, args=(stop,), daemon=True)]
        threads += [
            threading.Thread(target=self._runner, args=(stop,), daemon=True)
            for _ in range(self.concurrency)
        ]
        for t in threads:
            t.start()
        stop.wait()
        self._wake.set()
        for t in threads[1:]:
            t.join(timeout=self.lease_seconds)

    def _runner(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                if self.run_once():
                    continue
            except Exception:  # noqa: BLE001 - the loop must outlive a bad claim
                logger.exception("claim failed")
            self._wake.wait(self.poll_seconds)
            self._wake.clear()

    def _listen(self, stop: threading.Event) -> None:
        if self.listen_url is None:
            return
        while not stop.is_set():
            try:
                with psycopg.connect(self.listen_url, autocommit=True) as conn:
                    conn.execute("listen vp_jobs")
                    while not stop.is_set():
                        for note in conn.notifies(timeout=1.0):
                            if note.payload in self.kinds:
                                self._wake.set()
            except Exception:  # noqa: BLE001 - reconnect; polling covers the gap
                logger.exception("job listener lost its connection")
                stop.wait(2.0)


# -------------------------------------------------------------- scheduling


def next_fire(cron: str, timezone: str, after: datetime) -> datetime:
    """The next time a cron expression fires after `after`, in UTC.

    The expression is read in the schedule's IANA time zone, so "0 9 * * *"
    in Europe/London is nine in the morning there, in summer and winter.
    """
    from zoneinfo import ZoneInfo

    from croniter import croniter

    local = after.astimezone(ZoneInfo(timezone))
    fired = croniter(cron, local).get_next(datetime)
    return fired.astimezone(UTC)


def fire_due_schedules(pool: ConnectionPool, now: datetime | None = None) -> int:
    """Enqueue every schedule that is due and move it on; returns how many."""
    now = now or datetime.now(tz=UTC)
    fired = 0
    with pool.connection() as conn:
        due = conn.execute("select * from vp_schedules_due()").fetchall()
        for schedule_id, cron, timezone, next_run_at in due:
            following = next_fire(cron, timezone, max(now, next_run_at))
            conn.execute(
                "select vp_schedules_fire(%s, %s, %s)",
                (schedule_id, next_run_at, following),
            )
            fired += 1
    return fired


def ensure_scheduler(pool: ConnectionPool, now: datetime | None = None) -> None:
    """Make sure a scheduler job is queued for the coming minute.

    The key is the minute, so however many workers call this, one job per
    minute is queued; a scheduler that died is replaced a minute later.
    """
    now = now or datetime.now(tz=UTC)
    minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    enqueue_platform(
        pool,
        "scheduler",
        idempotency_key=f"scheduler:{minute:%Y%m%dT%H%M}",
        priority=PRIORITY_SCHEDULED,
        run_after=minute,
    )


def run_scheduler(ctx: JobContext) -> dict[str, Any]:
    """The scheduler job: reap lost leases, fire due schedules, queue the next."""
    with ctx.pool.connection() as conn:
        (reaped,) = conn.execute("select vp_jobs_reap()").fetchone() or (0,)
    fired = fire_due_schedules(ctx.pool)
    ensure_scheduler(ctx.pool)
    return {"reaped": reaped, "fired": fired}
