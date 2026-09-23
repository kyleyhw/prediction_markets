"""The job handlers end to end: the engine run by a worker over the shared
store, writing to a workspace's tables and to nobody else's."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import needs_db
from tests.test_forecast import root  # noqa: F401 - fixture
from tests.test_paper import make_source, resolved_record
from vp.domains import CS2
from vp.markets.snapshot import collect_snapshot
from vp.platform import jobs
from vp.platform.config import Settings
from vp.platform.db import tenant_session
from vp.platform.handlers import Services, handlers
from vp.platform.jobs import Worker, enqueue
from vp.platform.ledger import PgLedger
from vp.platform.storage import LocalStore, SharedRoot, publish_dataset, publish_tree
from vp.platform.views import WorkspaceView

pytestmark = needs_db


@pytest.fixture
def services(app_pool, pg_owner, root: Path, tmp_path: Path) -> Services:  # noqa: F811
    with pg_owner.transaction():
        pg_owner.execute("delete from forecast_memo")
        pg_owner.execute("delete from resolutions")
        pg_owner.execute("delete from tracked_markets")
        pg_owner.execute("delete from settled_markets")
    store = LocalStore(tmp_path / "store")
    publish_dataset(
        store, "epl", root / "markets/epl/resolved.parquet", "20260901T000000Z"
    )
    publish_tree(store, root, "shared", ["histories"])
    # One capture of the fake CS2 market, as the market-data service writes.
    snap, _ = collect_snapshot(CS2, make_source([]), tmp_path / "capture", depth=1)
    store.put_file(f"shared/snapshots/cs2/{snap.name}", snap)
    return Services(
        settings=Settings(database_url="unused", data_root=tmp_path),
        pool=app_pool,
        store=store,
        shared=SharedRoot(store, tmp_path / "cache"),
        source=lambda: make_source([resolved_record("resolved", "Yes")]),
        work_dir=tmp_path,
    )


def run_all(app_pool, services: Services, kinds: tuple[str, ...]) -> None:
    worker = Worker(app_pool, handlers(), kinds, services=services)
    while worker.run_once():
        pass


def job_row(pg_owner, job_id) -> dict[str, Any]:
    state, result, error = pg_owner.execute(
        "select state, result, error from jobs where id = %s", (job_id,)
    ).fetchone()
    return {"state": state, "result": result, "error": error}


def test_a_backtest_job_stores_its_run_for_its_workspace_only(
    app_pool, pg_owner, two_workspaces, services: Services
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    payload = {
        "domain": "epl",
        "forecasters": ["market", "constant"],
        "kinds": ["match"],
    }
    job_id = enqueue(app_pool, ada, "backtest", payload)
    run_all(app_pool, services, ("backtest",))
    row = job_row(pg_owner, job_id)
    assert row["state"] == "succeeded", row["error"]
    assert row["result"]["scored"] == 1 and row["result"]["cost_usd"] == 0
    with app_pool.connection() as conn, tenant_session(conn, ada):
        runs = conn.execute("select id, results, artifacts from runs").fetchall()
    assert len(runs) == 1 and runs[0][1]["common"] == 1
    assert services.store.get_bytes(f"{runs[0][2]}/results.json")
    with app_pool.connection() as conn, tenant_session(conn, bob):
        assert conn.execute("select count(*) from runs").fetchone() == (0,)
    # Bob's identical backtest reuses the memoised statistical forecasts.
    again = enqueue(app_pool, bob, "backtest", payload)
    run_all(app_pool, services, ("backtest",))
    assert job_row(pg_owner, again)["result"]["memo_hits"] >= 2


def test_a_paper_cycle_trades_the_shared_capture_into_the_account_s_ledger(
    app_pool, pg_owner, two_workspaces, services: Services
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    with app_pool.connection() as conn, tenant_session(conn, ada):
        (account,) = conn.execute(
            "insert into paper_accounts (workspace_id, name, domains, forecasters, "
            "created_by) values (%s, 'Sample', %s, %s, %s) returning id",
            (ada.workspace, ["cs2"], ["constant"], ada.user_id),
        ).fetchone()
    cycle = enqueue(app_pool, ada, "paper_cycle", {"account_id": str(account)})
    run_all(app_pool, services, ("paper_cycle",))
    row = job_row(pg_owner, cycle)
    assert row["state"] == "succeeded", row["error"]
    assert row["result"]["domains"]["cs2"]["forecasts"] == 1
    ledger = PgLedger(app_pool, ada, account)
    kinds = [e["kind"] for e in ledger.entries()]
    assert kinds[:2] == ["cycle", "forecast"] and ledger.verify() is None
    first = next(iter(ledger.entries()))
    assert first["data"]["snapshot"].startswith("snapshots/cs2/")  # no server path
    with app_pool.connection() as conn, tenant_session(conn, ada):
        assert conn.execute("select count(*) from forecasts").fetchone() == (1,)
    with app_pool.connection() as conn, tenant_session(conn, bob):
        assert conn.execute("select count(*) from forecasts").fetchone() == (0,)
    # The market list shows the workspace's own latest forecast, and only its.
    shown = WorkspaceView(services.shared, app_pool, ada, services.store)
    assert [f["forecaster"] for f in shown.latest_forecasts("cs2")["6"]] == ["constant"]
    assert (
        WorkspaceView(services.shared, app_pool, bob, services.store).latest_forecasts(
            "cs2"
        )
        == {}
    )
    # Bob cannot run a cycle on Ada's account: the job fails, touching nothing.
    theirs = enqueue(app_pool, bob, "paper_cycle", {"account_id": str(account)})
    run_all(app_pool, services, ("paper_cycle",))
    assert "no such paper account" in (job_row(pg_owner, theirs)["error"] or "")
    # The cutoff is the capture's time, so Bob's own account trading the same
    # capture reuses Ada's memoised forecast instead of making another.
    memo = pg_owner.execute("select count(*) from forecast_memo").fetchone()
    with app_pool.connection() as conn, tenant_session(conn, bob):
        (own,) = conn.execute(
            "insert into paper_accounts (workspace_id, name, domains, forecasters, "
            "created_by) values (%s, 'Sample', %s, %s, %s) returning id",
            (bob.workspace, ["cs2"], ["constant"], bob.user_id),
        ).fetchone()
    enqueue(app_pool, bob, "paper_cycle", {"account_id": str(own)})
    run_all(app_pool, services, ("paper_cycle",))
    assert pg_owner.execute("select count(*) from forecast_memo").fetchone() == memo
    with app_pool.connection() as conn, tenant_session(conn, bob):
        (cutoff,) = conn.execute("select cutoff from forecasts").fetchone()
    stem = next((services.shared.root / "snapshots" / "cs2").glob("*.parquet")).stem
    assert cutoff.strftime("%Y%m%dT%H%M%SZ") == stem


def test_settlement_asks_the_venue_only_about_resolved_markets(
    app_pool, pg_owner, two_workspaces, services: Services
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    order = {
        "forecaster": "constant",
        "market_id": "6",
        "condition_id": "0x6",
        "question": "Spirit vs Team Falcons",
        "side": "yes",
        "price": 0.51,
        "shares": 7.0,
        "stake": 3.57,
        "p_hat": 0.9,
        "q": 0.5,
        "bankroll_before": 1000.0,
    }
    results = []
    for who in (ada, bob):
        with app_pool.connection() as conn, tenant_session(conn, who):
            (account,) = conn.execute(
                "insert into paper_accounts (workspace_id, name, domains, "
                "forecasters, created_by) values (%s, 'Settle', %s, %s, %s) "
                "returning id",
                (who.workspace, ["cs2"], ["constant"], who.user_id),
            ).fetchone()
        ledger = PgLedger(app_pool, who, account)
        ledger.append("order", order)
        job = enqueue(app_pool, who, "settle", {"account_id": str(account)})
        run_all(app_pool, services, ("settle",))
        results.append(job_row(pg_owner, job)["result"])
        kinds = [e["kind"] for e in ledger.entries()]
        assert kinds[-1] == "settlement" and ledger.verify() is None
    # Not in the resolutions table and not tracked: the venue is asked once,
    # by the first; the second reads the venue's record the first kept (the
    # fake venue answers only once, so a second request would fail).
    assert [r["settled"] for r in results] == [1, 1]
    assert [r["venue_requests"] for r in results] == [1, 0]


def test_platform_maintenance_jobs_run(app_pool, pg_owner, services: Services) -> None:
    # The test database outlives a run; an earlier run's jobs hold the keys.
    pg_owner.execute("delete from jobs where idempotency_key like 'test-%%'")
    for kind in ("partitions", "sweep"):
        job_id = jobs.enqueue_platform(app_pool, kind, idempotency_key=f"test-{kind}")
        run_all(app_pool, services, (kind,))
        assert job_row(pg_owner, job_id)["state"] == "succeeded"


def test_a_dataset_build_keeps_each_history_and_never_fetches_one_twice(
    app_pool, pg_owner, services: Services
) -> None:
    pg_owner.execute("delete from jobs where idempotency_key like 'test-%%'")
    added = []
    for n in (1, 2):
        job_id = jobs.enqueue_platform(
            app_pool, "dataset", {"domain": "epl"}, idempotency_key=f"test-ds-{n}"
        )
        run_all(app_pool, services, ("dataset",))
        row = job_row(pg_owner, job_id)
        assert row["state"] == "succeeded", row["error"]
        added.append(row["result"]["histories_added"])
    assert added[0] > 0 and added[1] == 0
    assert len(services.store.keys("shared/histories/epl/")) >= added[0]


def test_the_platform_trades_the_sample_account_everyone_reads(
    app_pool, pg_owner, two_workspaces, services: Services
) -> None:
    from vp.platform.sample import SampleLedger, sample_account

    pg_owner.execute("delete from jobs where idempotency_key like 'test-%%'")
    job_id = jobs.enqueue_platform(
        app_pool, "sample_cycle", idempotency_key="test-sample-cycle"
    )
    run_all(app_pool, services, ("sample_cycle",))
    row = job_row(pg_owner, job_id)
    assert row["state"] == "succeeded", row["error"]
    # Every domain the engine has, including those with no capture yet.
    assert row["result"]["domains"]["cs2"]["forecasts"] >= 1
    account = sample_account(app_pool)
    assert account is not None and account["head_seq"] >= 1
    ledger = SampleLedger(app_pool, account["id"], None)
    assert ledger.verify() is None
    assert any(e["kind"] == "cycle" for e in ledger.entries())
    with pytest.raises(PermissionError):
        ledger.append("cycle", {})
