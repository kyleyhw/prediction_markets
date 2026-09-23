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
from vp.platform.config import Settings
from vp.platform.handlers import Services, handlers
from vp.platform.jobs import Worker
from vp.platform.mail import OutboxMailer
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


def test_starting_paper_trading_opens_an_account_schedules_and_a_first_cycle(
    world,
) -> None:
    client = world["client"]
    ada, bob = people(world)
    started = _as(client, ada).post(
        "/api/paper/start",
        json={"domains": ["epl"], "timezone": "Europe/London"},
        headers=ORIGIN,
    )
    assert started.status_code == 201, started.text
    job_id = started.json()["job_id"]
    again = client.post("/api/paper/start", json={}, headers=ORIGIN)
    assert again.status_code == 409
    overview = client.get("/api/overview").json()
    assert overview["account"]["domains"] == ["epl"]
    jobs = client.get("/api/jobs").json()
    assert [j["kind"] for j in jobs] == ["paper_cycle"] and jobs[0]["id"] == job_id
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "queued"
    # Bob sees none of it, and cannot cancel Ada's job.
    _as(client, bob)
    assert client.get("/api/overview").json()["account"] is None
    assert client.get("/api/jobs").json() == []
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=ORIGIN).status_code == 404
    assert client.get("/api/paper/export").status_code == 404
    # Ada cancels her own.
    _as(client, ada)
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=ORIGIN).status_code == 202
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "cancelled"
    bad = client.post(
        "/api/paper/start", json={"timezone": "Mars/Olympus"}, headers=ORIGIN
    )
    assert bad.status_code == 422


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
