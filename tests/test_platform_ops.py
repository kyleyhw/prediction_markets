"""The operator's commands: halts, pauses, budgets, drains and retries, each
recorded in the audit chain with the operator who did it."""

from __future__ import annotations

from decimal import Decimal

from tests.conftest import needs_db
from vp.platform import audit, budgets, ops
from vp.platform.jobs import Worker, enqueue

pytestmark = needs_db


def test_a_halt_stops_work_and_the_audit_chain_names_the_operator(
    app_pool, pg_owner, two_workspaces
) -> None:
    ada = two_workspaces["a"]
    before = len(audit.entries(pg_owner))
    ops.halt(pg_owner, "venue outage")
    assert [h["scope"] for h in ops.active_halts(pg_owner)] == ["platform"]
    enqueue(app_pool, ada, "settle", {})
    worker = Worker(app_pool, {"settle": lambda c: {}}, ("settle",))
    assert not worker.run_once()
    assert ops.resume(pg_owner) == 1
    assert worker.run_once()
    ops.halt(pg_owner, "abuse report", ada.workspace)
    assert ops.resume(pg_owner, ada.workspace) == 1
    tail = audit.entries(pg_owner)[before:]
    assert [e["kind"] for e in tail] == [
        "platform.halt",
        "platform.resume",
        "workspace.pause",
        "workspace.resume",
    ]
    assert all(e["data"]["principal"]["subject"].startswith("operator:") for e in tail)
    assert audit.verify(pg_owner) is None


def test_a_budget_limits_what_a_workspace_may_reserve(
    app_pool, pg_owner, two_workspaces
) -> None:
    import pytest

    ada = two_workspaces["a"]
    assert budgets.standing(app_pool, ada).limit_usd == budgets.DEFAULT_LIMIT_USD
    ops.set_budget(pg_owner, ada.workspace, Decimal("1.00"))
    budgets.reserve(app_pool, ada, 0.60)
    with pytest.raises(budgets.OverBudget, match="0.40"):
        budgets.reserve(app_pool, ada, 0.60)
    job = enqueue(app_pool, ada, "backtest", {}, reserved_usd=0.60)
    charged = budgets.settle_job(
        app_pool, ada, job, 0.60, [{"forecaster": "llm", "domain": "epl", "usd": 0.25}]
    )
    assert charged == Decimal("0.25")
    standing = budgets.standing(app_pool, ada)
    assert standing.charged_usd == Decimal("0.25") and standing.reserved_usd == 0
    assert standing.remaining_usd == Decimal("0.75")
    assert budgets.breakdown(app_pool, ada)[0]["forecaster"] == "llm"
    # Bob sees none of Ada's spending.
    assert budgets.standing(app_pool, two_workspaces["b"]).charged_usd == 0


def test_a_dead_job_can_be_retried_and_a_kind_drained(
    app_pool, pg_owner, two_workspaces
) -> None:
    ada = two_workspaces["a"]
    job = enqueue(app_pool, ada, "leakage", {})
    with pg_owner.transaction():
        pg_owner.execute(
            "update jobs set state = 'dead', attempts = 3 where id = %s", (job,)
        )
    assert ops.retry_job(pg_owner, job)
    assert (ops.show_job(pg_owner, job) or {}).get("state") == "queued"
    ops.set_drain(pg_owner, "leakage", True)
    worker = Worker(app_pool, {"leakage": lambda c: {}}, ("leakage",))
    assert not worker.run_once()
    ops.set_drain(pg_owner, "leakage", False)
    assert worker.run_once()
    assert (ops.show_job(pg_owner, job) or {}).get("state") == "succeeded"


def test_a_data_refresh_does_what_the_daily_build_does(pg_owner) -> None:
    pg_owner.execute(
        "insert into schedules (name, kind, payload, cron, timezone, next_run_at) "
        "values ('dataset-testland', 'dataset', "
        '\'{"domain": "testland", "history_limit": 7}\', \'0 4 * * *\', '
        "'UTC', now() + interval '1 day')"
    )
    ids = ops.refresh(pg_owner, "testland", ("dataset",))
    payload = pg_owner.execute(
        "select payload from jobs where id = %s", (ids[0],)
    ).fetchone()[0]
    pg_owner.execute("delete from jobs where id = %s", (ids[0],))
    pg_owner.execute("delete from schedules where name = 'dataset-testland'")
    assert payload["history_limit"] == 7


def test_a_job_scheduled_for_later_is_not_waiting(
    app_pool, pg_owner, two_workspaces
) -> None:
    from datetime import UTC, datetime, timedelta

    ada = two_workspaces["a"]
    later = enqueue(
        app_pool,
        ada,
        "leakage",
        {},
        run_after=datetime.now(tz=UTC) + timedelta(hours=1),
    )
    rows = {(k, s): (n, age) for k, s, n, age in ops.queue_depth(pg_owner)}
    pg_owner.execute("delete from jobs where id = %s", (later,))
    assert rows[("leakage", "queued")][0] >= 1
    assert rows[("leakage", "queued")][1] is None  # nothing ready is waiting
