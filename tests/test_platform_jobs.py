"""The job queue against Postgres: claiming, leases, retries, cancellation,
halts, drains, schedules, and the tenancy boundary around all of it."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import needs_db
from vp.platform import jobs
from vp.platform.jobs import JobContext, Worker, enqueue, next_fire

pytestmark = needs_db


@pytest.fixture(autouse=True)
def clean_queue(pg_owner):
    """Each test starts with no queued platform work, halts or drains."""
    with pg_owner.transaction():
        pg_owner.execute("delete from jobs where workspace_id is null")
        pg_owner.execute("update halts set cleared_at = now() where cleared_at is null")
        pg_owner.execute("delete from ops_flags")
        pg_owner.execute("delete from schedules")
    yield


def state(pg_owner, job_id):
    return pg_owner.execute(
        "select state, attempts, error, result, progress from jobs where id = %s",
        (job_id,),
    ).fetchone()


def test_a_job_runs_as_the_person_who_asked(app_pool, pg_owner, two_workspaces) -> None:
    ada = two_workspaces["a"]
    seen = {}

    def handler(ctx: JobContext):
        seen["principal"] = ctx.principal
        ctx.progress(0.5, "halfway")
        return {"answer": 42}

    job_id = enqueue(app_pool, ada, "backtest", {"domain": "epl"})
    worker = Worker(app_pool, {"backtest": handler}, ("backtest",))
    assert worker.run_once()
    st, attempts, error, result, progress = state(pg_owner, job_id)
    assert (st, attempts, error, result) == ("succeeded", 1, None, {"answer": 42})
    assert progress["fraction"] == 1
    p = seen["principal"]
    assert p.workspace == ada.workspace and p.subject == ada.subject and p.attributable
    assert not worker.run_once()  # nothing left


def test_two_workers_never_take_the_same_job(app_pool, two_workspaces) -> None:
    ada = two_workspaces["a"]
    ids = {enqueue(app_pool, ada, "settle", {"n": n}) for n in range(20)}
    taken: list = []
    lock = threading.Lock()

    def handler(ctx):
        with lock:
            taken.append(ctx.job.id)

    workers = [Worker(app_pool, {"settle": handler}, ("settle",)) for _ in range(4)]

    def drain(w):
        while w.run_once():
            pass

    threads = [threading.Thread(target=drain, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(taken) == sorted(ids) and len(set(taken)) == 20


def test_a_failing_job_retries_then_goes_dead(
    app_pool, pg_owner, two_workspaces
) -> None:
    ada = two_workspaces["a"]
    job_id = enqueue(app_pool, ada, "leakage", {})

    def boom(ctx):
        raise RuntimeError("no backtest to compare with")

    worker = Worker(app_pool, {"leakage": boom}, ("leakage",))
    assert worker.run_once()
    st, attempts, error, *_ = state(pg_owner, job_id)
    assert st == "queued" and attempts == 1 and "no backtest" in error
    # It waits out its backoff before it can be claimed again.
    assert not worker.run_once()
    for _ in range(2):
        with pg_owner.transaction():
            pg_owner.execute(
                "update jobs set run_after = now() where id = %s", (job_id,)
            )
        assert worker.run_once()
    assert state(pg_owner, job_id)[0] == "dead"


def test_cancelling_stops_a_queued_job_and_a_running_one(
    app_pool, pg_owner, two_workspaces
) -> None:
    ada = two_workspaces["a"]
    queued = enqueue(app_pool, ada, "backtest", {})
    assert jobs.request_cancel(app_pool, ada, queued)
    assert state(pg_owner, queued)[0] == "cancelled"

    running = enqueue(app_pool, ada, "backtest", {})

    def slow(ctx):
        jobs.request_cancel(app_pool, ada, ctx.job.id)
        ctx.progress(1.0)  # the report after the request raises JobCancelled
        return {"finished": True}

    Worker(app_pool, {"backtest": slow}, ("backtest",)).run_once()
    assert state(pg_owner, running)[0] == "cancelled"


def test_nothing_is_claimed_while_halted_or_drained(
    app_pool, pg_owner, two_workspaces
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    ran: list = []
    worker = Worker(app_pool, {"settle": lambda c: ran.append(c.job.id)}, ("settle",))
    a_job = enqueue(app_pool, ada, "settle", {})
    b_job = enqueue(app_pool, bob, "settle", {})
    with pg_owner.transaction():
        pg_owner.execute(
            "insert into halts (scope, workspace_id, reason, set_by) "
            "values ('workspace', %s, 'test', 'operator')",
            (ada.workspace,),
        )
    assert worker.run_once() and ran == [b_job]  # only Bob's runs
    assert not worker.run_once()
    with pg_owner.transaction():
        pg_owner.execute("update halts set cleared_at = now()")
        pg_owner.execute(
            "insert into halts (scope, reason, set_by) values ('platform', 'test', 'operator')"
        )
    assert not worker.run_once()  # the platform halt stops everything
    with pg_owner.transaction():
        pg_owner.execute("update halts set cleared_at = now()")
        pg_owner.execute(
            """insert into ops_flags (name, value) values ('drain:settle', 'true')"""
        )
    assert not worker.run_once()  # a drained kind is not claimed
    with pg_owner.transaction():
        pg_owner.execute("delete from ops_flags")
    assert worker.run_once() and ran == [b_job, a_job]


def test_a_lost_worker_s_job_is_taken_back(app_pool, pg_owner, two_workspaces) -> None:
    ada = two_workspaces["a"]
    job_id = enqueue(app_pool, ada, "backtest", {})
    worker = Worker(app_pool, {"backtest": lambda c: {}}, ("backtest",))
    job = worker.claim()
    assert job is not None
    with pg_owner.transaction():
        pg_owner.execute(
            "update jobs set lease_until = now() - interval '1 second' where id = %s",
            (job_id,),
        )
    with app_pool.connection() as conn:
        (reaped,) = conn.execute("select vp_jobs_reap()").fetchone()
    assert reaped == 1 and state(pg_owner, job_id)[0] == "queued"
    # The first worker, if it comes back, can no longer record an outcome.
    assert worker.execute(job) == "lost"


def test_one_workspace_cannot_see_or_cancel_another_s_jobs(
    app_pool, two_workspaces
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    job_id = enqueue(app_pool, ada, "backtest", {"secret": "ada's"})
    assert [j["id"] for j in jobs.workspace_jobs(app_pool, ada)] == [job_id]
    assert jobs.workspace_jobs(app_pool, bob) == []
    assert not jobs.request_cancel(app_pool, bob, job_id)


def test_asking_twice_with_a_key_queues_once(app_pool, two_workspaces) -> None:
    ada = two_workspaces["a"]
    first = enqueue(app_pool, ada, "paper_cycle", {}, idempotency_key="k1")
    assert enqueue(app_pool, ada, "paper_cycle", {}, idempotency_key="k1") == first
    with pytest.raises(ValueError):
        enqueue(app_pool, ada, "dataset", {})  # platform work is not a workspace's


def test_schedules_fire_once_per_time_in_their_own_zone(
    app_pool, pg_owner, two_workspaces
) -> None:
    ada = two_workspaces["a"]
    past = datetime.now(tz=UTC) - timedelta(minutes=5)
    with pg_owner.transaction():
        pg_owner.execute(
            "insert into schedules (workspace_id, created_by, name, kind, payload, cron, "
            "timezone, next_run_at) values (%s, %s, 'hourly', 'paper_cycle', '{}', "
            "'0 * * * *', 'Europe/London', %s)",
            (ada.workspace, ada.user_id, past),
        )
    assert jobs.fire_due_schedules(app_pool) == 1
    assert jobs.fire_due_schedules(app_pool) == 0  # moved on to the next hour
    queued = jobs.workspace_jobs(app_pool, ada)
    assert [j["kind"] for j in queued] == ["paper_cycle"]
    (nxt,) = pg_owner.execute("select next_run_at from schedules").fetchone()
    assert nxt > datetime.now(tz=UTC) and nxt.minute == 0


def test_cron_is_read_in_the_schedule_s_time_zone() -> None:
    # 09:00 in London is 08:00 UTC in summer and 09:00 UTC in winter.
    summer = next_fire(
        "0 9 * * *", "Europe/London", datetime(2026, 7, 1, 12, tzinfo=UTC)
    )
    winter = next_fire(
        "0 9 * * *", "Europe/London", datetime(2026, 12, 1, 12, tzinfo=UTC)
    )
    assert (summer.hour, winter.hour) == (8, 9)


def test_the_scheduler_queues_itself_for_the_next_minute(app_pool, pg_owner) -> None:
    jobs.ensure_scheduler(app_pool)
    jobs.ensure_scheduler(app_pool)  # idempotent within the minute
    (n,) = pg_owner.execute(
        "select count(*) from jobs where kind = 'scheduler' and state = 'queued'"
    ).fetchone()
    assert n == 1


def test_a_new_job_wakes_a_waiting_worker(app_pool, two_workspaces) -> None:
    """LISTEN/NOTIFY: a job queued while the worker sleeps starts well before
    the worker's poll interval would have come round."""
    from tests.conftest import APP_URL

    ada = two_workspaces["a"]
    started = threading.Event()
    worker = Worker(
        app_pool,
        {"backtest": lambda c: started.set()},
        ("backtest",),
        poll_seconds=30,
        listen_url=APP_URL,
    )
    stop = threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop,), daemon=True)
    thread.start()
    try:
        threading.Event().wait(1.0)  # the worker is now idle and listening
        enqueue(app_pool, ada, "backtest", {})
        assert started.wait(5.0)
    finally:
        stop.set()
        thread.join(timeout=10)
