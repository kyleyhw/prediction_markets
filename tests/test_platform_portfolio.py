"""Risk, strategy health and promotion on the platform (docs/portfolio.md,
tasks 98 and 100 to 102): the x-ray of open paper positions, the health
check pausing a decayed strategy and a person resuming it, and the
promotion protocol with its audit rows and a person's approval."""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from tests.test_platform_collab import _strategy
from tests.test_platform_web import (  # noqa: F401 - fixtures
    ORIGIN,
    _as,
    _email,
    _sign_in,
    client,
    mailer,
    owner,
    pytestmark,
)
from vp.platform import portfolio
from vp.platform.auth import resolve_session
from vp.platform.ledger import PgLedger
from vp.platform.mail import OutboxMailer


def test_risk_health_and_promotion(
    client: TestClient,  # noqa: F811
    mailer: OutboxMailer,  # noqa: F811
    owner,  # noqa: F811
    app_pool,
) -> None:
    ada = _email()
    cookie = _sign_in(client, mailer, ada)
    _as(client, cookie)
    sid = _strategy(client, owner, ada)
    assert client.post(f"/api/strategies/{sid}/paper", headers=ORIGIN).status_code in (
        200,
        201,
        202,
    )
    with app_pool.connection() as conn:
        me = resolve_session(conn, cookie)
    assert me is not None
    (account, version) = owner.execute(
        "select a.id, a.strategy_version_id from paper_accounts a "
        "join strategy_versions v on v.id = a.strategy_version_id "
        "where v.strategy_id = %s",
        (sid,),
    ).fetchone()
    ledger = PgLedger(app_pool, me, account)
    # Two markets of one exclusive event, bought together: at most one can win.
    for market, price in (("m1", 0.3), ("m2", 0.4)):
        ledger.append(
            "order",
            {
                "forecaster": "elo",
                "market_id": market,
                "event_id": "day",
                "domain": "epl",
                "side": "yes",
                "price": price,
                "shares": 100.0,
                "stake": 100.0 * price,
                "q": price,
                "p_hat": price + 0.1,
                "neg_risk": True,
                "end_date": "2099-01-01T12:00:00Z",
            },
        )
    x = client.get("/api/risk").json()["all"]
    assert x["positions"] == 2 and x["worst_case"] == -70.0
    assert x["by_event"][0]["group"] == "day"

    # Sixty settlements, each far worse than the market: decayed, paused.
    for i in range(60):
        ledger.append(
            "settlement",
            {
                "forecaster": "elo",
                "market_id": f"s{i}",
                "label": 1,
                "pnl": -1.0,
                "brier": 0.4 + 0.05 * (i % 3),
                "brier_market": 0.1,
            },
        )
    report = portfolio.check_health(app_pool, me, UUID(sid))
    assert report["state"] == "decayed" and report["transitions"][-1]["to"] == "decayed"
    assert portfolio.paused(app_pool, me, version)
    notices = client.get("/api/notifications").json()["items"]
    assert any(n["kind"] == "health" and "decayed" in n["title"] for n in notices)
    got = client.get(f"/api/strategies/{sid}/health").json()["health"]
    assert got["state"] == "decayed" and got["paused"]
    resumed = client.post(f"/api/strategies/{sid}/health/resume", headers=ORIGIN)
    assert resumed.json() == {"resumed": True}
    assert not portfolio.paused(app_pool, me, version)

    # Promotion: nothing passes without a backtest; paper is advisory.
    paper = client.post(
        f"/api/strategies/{sid}/promotion", json={"target": "paper"}, headers=ORIGIN
    ).json()
    assert not paper["passed"] and not paper["binding"]
    assert [c["n"] for c in paper["criteria"]] == [1, 2]
    live = client.post(
        f"/api/strategies/{sid}/promotion", json={"target": "live"}, headers=ORIGIN
    ).json()
    assert [c["n"] for c in live["criteria"]] == [1, 2, 3, 4, 5, 6]
    assert not live["passed"]
    assert (
        client.post(f"/api/promotions/{live['id']}/approve", headers=ORIGIN).status_code
        == 409
    )
    (rows,) = owner.execute(
        "select count(*) from audit_entries where kind = 'promotion.criterion' "
        "and entry -> 'data' ->> 'evaluation_id' = %s",
        (live["id"],),
    ).fetchone()
    assert rows == 6
    # A passing evaluation is approved by a person on the page, not a token.
    with owner.transaction():
        owner.execute(
            "update promotion_evaluations set passed = true where id = %s",
            (live["id"],),
        )
    token = client.post(
        "/api/tokens", json={"name": "agent", "scope": "write"}, headers=ORIGIN
    ).json()["token"]
    client.cookies.clear()
    refused = client.post(
        f"/api/promotions/{live['id']}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert refused.status_code == 403
    _as(client, cookie)
    assert (
        client.post(f"/api/promotions/{live['id']}/approve", headers=ORIGIN).status_code
        == 204
    )
    listed = client.get(f"/api/strategies/{sid}/promotion").json()["evaluations"]
    assert listed[0]["approved_at"] is not None
