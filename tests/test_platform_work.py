"""Starting work from the page: paper trading, backtests, jobs, spending,
keys and metrics, through the web service, as two people who must not see
each other's."""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.conftest import APP_URL, needs_db
from tests.test_forecast import EPL
from tests.test_platform_web import ORIGIN, _as, _email, _sign_in
from vp.markets.store import write_markets
from vp.paper.ledger import Ledger
from vp.platform.auth import resolve_session
from vp.platform.config import Settings
from vp.platform.handlers import Services, handlers
from vp.platform.jobs import Worker
from vp.platform.ledger import PgLedger
from vp.platform.mail import OutboxMailer
from vp.platform.sample import ensure_sample_account, sample_principal
from vp.platform.storage import LocalStore, SharedRoot, publish_dataset
from vp.platform.web import create_app

pytestmark = needs_db
MASTER = base64.b64encode(os.urandom(32)).decode()


@pytest.fixture(scope="module")
def world(pg_owner, tmp_path_factory) -> Iterator[dict]:
    root = tmp_path_factory.mktemp("work")
    store = LocalStore(root / "store")
    dataset = root / "resolved.parquet"
    write_markets(dataset, EPL)
    publish_dataset(store, "epl", dataset, "20260901T000000Z")
    settings = Settings(
        database_url=APP_URL,
        data_root=root,
        public_url="http://testserver",
        master_key=MASTER,
        metrics_token="scrape-me",  # pragma: allowlist secret
    )
    mailer = OutboxMailer()
    app = create_app(settings, mailer=mailer, store=store, sign_in_limit=100_000)
    with TestClient(app) as client:
        yield {
            "client": client,
            "mailer": mailer,
            "store": store,
            "root": root,
            "settings": settings,
        }


def people(world) -> tuple[str, str]:
    c, m = world["client"], world["mailer"]
    return _sign_in(c, m, _email()), _sign_in(c, m, _email())


def test_everyone_reads_the_one_sample_account_and_only_the_platform_writes_it(
    world, app_pool
) -> None:
    client = world["client"]
    ada, bob = people(world)
    account = ensure_sample_account(app_pool)
    ledger = PgLedger(app_pool, sample_principal(), account)
    ledger.append("cycle", {"domain": "epl", "markets": 1})
    entries = []
    for who in (ada, bob):
        _as(client, who)
        overview = client.get("/api/overview").json()
        assert overview["sample"] is True and overview["account"] is None
        entries.append(client.get("/api/paper").json()["entries"])
        # The sample runs on its own; nobody starts or runs it from the page.
        assert client.post("/api/paper/run", headers=ORIGIN).status_code == 409
        assert client.post("/api/paper/start", json={}, headers=ORIGIN).status_code in (
            404,
            405,
        )
        exported = client.get("/api/paper/export")
        assert exported.status_code == 200
        path = world["root"] / "sample.jsonl"
        path.write_text(exported.text)
        assert Ledger(path).verify() is None
    assert entries[0] == entries[1] >= 1
    # A workspace cannot write to the sample account, even naming it.
    with app_pool.connection() as conn:
        principal = resolve_session(conn, bob)
    assert principal is not None
    with pytest.raises(Exception):  # noqa: B017 - row-level security refuses it
        PgLedger(app_pool, principal, account).append("cycle", {"domain": "epl"})
    # The reserved address the platform acts as cannot be signed in.
    client.cookies.clear()
    asked = client.post(
        "/auth/sign-in", data={"email": "platform@vibe-predict.invalid"}, headers=ORIGIN
    )
    assert asked.status_code == 422


def test_a_job_is_cancelled_by_its_workspace_only(world) -> None:
    client = world["client"]
    ada, bob = people(world)
    body = {"domain": "epl", "forecasters": ["market"], "kinds": ["match"]}
    job_id = (
        _as(client, ada)
        .post("/api/backtests", json=body, headers=ORIGIN)
        .json()["job_id"]
    )
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "queued"
    _as(client, bob)
    assert client.get("/api/jobs").json() == []
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=ORIGIN).status_code == 404
    _as(client, ada)
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=ORIGIN).status_code == 202
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "cancelled"


def test_a_backtest_from_the_page_is_estimated_run_and_its_files_kept_private(
    world, app_pool, pg_owner
) -> None:
    client = world["client"]
    ada, bob = people(world)
    body = {"domain": "epl", "forecasters": ["market", "constant"], "kinds": ["match"]}
    estimate = _as(client, ada).post(
        "/api/backtests/estimate", json=body, headers=ORIGIN
    )
    assert estimate.status_code == 200
    assert estimate.json()["estimate_usd"] == 0 and estimate.json()["markets"] == 6
    capped = client.post(
        "/api/backtests/estimate", json=body | {"max_markets": 2}, headers=ORIGIN
    )
    assert capped.json()["markets"] == 2
    started = client.post("/api/backtests", json=body, headers=ORIGIN)
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    services = Services(
        settings=world["settings"],
        pool=app_pool,
        store=world["store"],
        shared=SharedRoot(world["store"], world["root"] / "worker-cache"),
        work_dir=world["root"],
    )
    Worker(app_pool, handlers(), ("backtest",), services=services).run_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "succeeded", job["error"]
    runs = client.get("/api/backtests").json()
    assert len(runs) == 1 and runs[0]["results"]["config"]["domain"] == "epl"
    run_id = job["result"]["run_id"]
    assert client.get(f"/api/runs/{run_id}/summary.md").status_code == 200
    assert client.get(f"/api/runs/{run_id}/..%2Fsecret.md").status_code == 404
    _as(client, bob)
    assert client.get("/api/backtests").json() == []
    assert client.get(f"/api/runs/{run_id}/summary.md").status_code == 404
    # Nonsense is refused before anything is queued.
    for bad in (
        {"domain": "nba"},
        {"domain": "epl", "forecasters": ["oracle"]},
        {"domain": "epl", "hours_before_close": 0},
        {"domain": "epl", "surprise": 1},
    ):
        assert (
            client.post("/api/backtests", json=bad, headers=ORIGIN).status_code == 422
        )


def test_a_model_backtest_needs_a_key_and_fits_the_budget(world) -> None:
    client = world["client"]
    ada, _ = people(world)
    body = {"domain": "epl", "forecasters": ["llm"], "kinds": ["match"]}
    _as(client, ada)
    assert client.get("/api/capabilities").json()["llm"] is False
    assert client.post("/api/backtests", json=body, headers=ORIGIN).status_code == 409
    estimate = client.post("/api/backtests/estimate", json=body, headers=ORIGIN).json()
    assert estimate["estimate_usd"] > 0 and estimate["limit_usd"] == 5.0
    batch = client.post(
        "/api/backtests/estimate", json=body | {"batch": True}, headers=ORIGIN
    )
    assert batch.json()["estimate_usd"] == pytest.approx(
        estimate["estimate_usd"] / 2, rel=1e-3
    )


def test_an_own_key_is_stored_encrypted_and_shown_only_as_a_hint(
    world, pg_owner
) -> None:
    client = world["client"]
    ada, bob = people(world)
    key = "sk-ant-" + "k" * 40  # pragma: allowlist secret
    stored = _as(client, ada).put("/api/keys", json={"key": key}, headers=ORIGIN)
    assert stored.status_code == 200 and stored.json()["hint"] == "…kkkk"
    assert client.get("/api/keys").json()["hint"] == "…kkkk"
    assert client.get("/api/capabilities").json()["llm"] is True
    _as(client, bob)
    assert client.get("/api/keys").json()["hint"] is None
    _as(client, ada)
    assert client.delete("/api/keys", headers=ORIGIN).status_code == 204
    assert client.get("/api/keys").json()["hint"] is None


def test_spending_refresh_and_metrics(world) -> None:
    client = world["client"]
    ada, _ = people(world)
    spend = _as(client, ada).get("/api/spend").json()
    assert spend["limit_usd"] == 5.0 and spend["charged_usd"] == 0
    client.post("/api/refresh/epl", headers=ORIGIN)
    # Within fifteen minutes a second ask, by anyone, queues nothing more.
    assert client.post("/api/refresh/epl", headers=ORIGIN).json()["queued"] is False
    assert client.post("/api/refresh/nba", headers=ORIGIN).status_code == 404
    _as(client, None)
    assert client.get("/metrics").status_code == 404
    scraped = client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
    assert scraped.status_code == 200 and "vp_http_requests_total" in scraped.text


def test_the_paper_view_is_kept_per_ledger_head_and_never_stale(
    world, app_pool
) -> None:
    client = world["client"]
    ada, _ = people(world)
    account = ensure_sample_account(app_pool)
    before = _as(client, ada).get("/api/paper").json()["entries"]
    assert client.get("/api/paper").json()["entries"] == before
    PgLedger(app_pool, sample_principal(), account).append("cycle", {"domain": "epl"})
    # The head moved, so the next answer is computed afresh.
    assert client.get("/api/paper").json()["entries"] == before + 1
    assert client.get("/api/overview").json()["paper"]["entries"] == before + 1


def test_deleting_an_account_removes_everything_of_it_and_nothing_else(
    world, app_pool, pg_owner
) -> None:
    client = world["client"]
    ada, bob = people(world)
    body = {"domain": "epl", "forecasters": ["market", "constant"], "kinds": ["match"]}
    _as(client, ada).post("/api/backtests", json=body, headers=ORIGIN)
    services = Services(
        settings=world["settings"],
        pool=app_pool,
        store=world["store"],
        shared=SharedRoot(world["store"], world["root"] / "worker-cache"),
        work_dir=world["root"],
    )
    Worker(app_pool, handlers(), ("backtest",), services=services).run_once()
    client.put("/api/settings", json={"theme": "dark"}, headers=ORIGIN)
    client.post("/api/tokens", json={"name": "laptop"}, headers=ORIGIN)
    me = client.get("/auth/me").json()
    workspace, email = me["workspace"]["id"], me["email"]
    assert world["store"].keys(f"workspaces/{workspace}/")
    _as(client, bob).post("/api/backtests", json=body, headers=ORIGIN)
    _as(client, ada)
    wrong = client.request(
        "DELETE", "/api/account", json={"confirm": "yes"}, headers=ORIGIN
    )
    assert wrong.status_code == 422
    done = client.request(
        "DELETE", "/api/account", json={"confirm": "delete my account"}, headers=ORIGIN
    )
    assert done.status_code == 200
    assert _as(client, ada).get("/api/overview").status_code == 401
    left = {
        table: pg_owner.execute(
            f"select count(*) from {table} where workspace_id = %s",  # noqa: S608
            (workspace,),
        ).fetchone()[0]
        for table in ("runs", "jobs", "api_tokens", "sessions", "memberships")
    }
    assert left == dict.fromkeys(left, 0)
    assert pg_owner.execute(
        "select count(*) from users where email = %s", (email,)
    ).fetchone() == (0,)
    assert world["store"].keys(f"workspaces/{workspace}/") == []
    (logged,) = pg_owner.execute(
        "select count(*) from audit_entries where entry->>'kind' = 'account.delete' "
        "and entry->'data'->>'workspace' = %s",
        (workspace,),
    ).fetchone()
    assert logged == 1
    # Bob's work is untouched.
    assert len(_as(client, bob).get("/api/jobs").json()) == 1
