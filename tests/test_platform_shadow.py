"""Shadow imports on the platform (docs/shadow.md, tasks 92 and 96): consent,
the import job over the synthetic record of `test_shadow.py` with the venue
replaced, the card, its export, trying the rule as a strategy, the optional
proof of ownership, and privacy between teammates."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from eth_hash.auto import keccak
from eth_keys import keys
from fastapi.testclient import TestClient

from tests.test_platform_collab import _invite_token
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
from tests.test_shadow import _activity, _history, root  # noqa: F401 - fixture
from vp.platform import shadow
from vp.platform.auth import resolve_session
from vp.platform.mail import OutboxMailer
from vp.platform.storage import LocalStore
from vp.shadow import card as shadow_card
from vp.venues import polymarket

KEY = keys.PrivateKey(bytes(range(1, 33)))
ADDRESS = KEY.public_key.to_checksum_address().lower()


def _sign(text: str) -> str:
    body = text.encode()
    digest = keccak(b"\x19Ethereum Signed Message:\n" + str(len(body)).encode() + body)
    sig = KEY.sign_msg_hash(digest)
    return "0x" + (sig.to_bytes()[:64] + bytes([sig.v + 27])).hex()


def test_an_address_is_imported_with_consent_read_and_tried(
    client: TestClient,  # noqa: F811
    mailer: OutboxMailer,  # noqa: F811
    app_pool,
    root: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch,
) -> None:
    cookie = _sign_in(client, mailer, _email())
    _as(client, cookie)
    assert client.get("/api/shadow").json()["consent"].startswith("This address")
    refused = client.post(
        "/api/shadow", json={"address": ADDRESS, "consent": False}, headers=ORIGIN
    )
    assert refused.status_code == 409
    bad = client.post(
        "/api/shadow",
        json={"address": "0x" + "z" * 40, "consent": True},
        headers=ORIGIN,
    )
    assert bad.status_code == 409
    made = client.post(
        "/api/shadow", json={"address": ADDRESS, "consent": True}, headers=ORIGIN
    )
    assert made.status_code == 202, made.text
    iid = made.json()["id"]
    assert client.get("/api/shadow").json()["imports"][0]["state"] == "queued"

    # The job, with the venue replaced by the synthetic record.
    monkeypatch.setattr(
        polymarket, "fetch_activity", lambda a, max_items: iter(_activity())
    )
    monkeypatch.setattr(polymarket, "fetch_resolution", lambda c: None)
    monkeypatch.setattr(polymarket, "fetch_leaderboard", lambda c, limit: [])
    monkeypatch.setattr(polymarket, "fetch_user_pnl", lambda a: [{"t": 1.0, "p": 2.0}])
    monkeypatch.setattr(shadow_card, "venue_history", _history)
    with app_pool.connection() as conn:
        me = resolve_session(conn, cookie)
    store = LocalStore(tmp_path / "store")
    ctx = SimpleNamespace(
        services=SimpleNamespace(
            pool=app_pool,
            store=store,
            refresh=lambda domains: None,
            shared=SimpleNamespace(root=root),
        ),
        job=SimpleNamespace(principal=me, payload={"import_id": iid}),
        progress=lambda f, m: None,
    )
    assert shadow.run(ctx) == {"bets": 60, "scored": 60}
    assert me is not None
    assert store.get_bytes(f"shadow/{me.workspace}/{iid}/activity.json.gz")

    got = client.get(f"/api/shadow/{iid}").json()
    assert got["state"] == "done" and got["card"]["venue_pnl"] == [{"t": 1.0, "p": 2.0}]
    csv = client.get(f"/api/shadow/{iid}/card.csv")
    assert csv.status_code == 200 and csv.text.startswith("section,measure,value")
    domain = next(iter(got["card"]["rules"]))
    tried = client.post(
        f"/api/shadow/{iid}/try", json={"domain": domain, "index": 0}, headers=ORIGIN
    )
    assert tried.status_code == 201, tried.text
    convo = client.get(f"/api/conversations/{tried.json()['conversation_id']}").json()
    turn = convo["turns"][-1]
    assert turn["content"]["spec"]["rule"]["kind"] == "follow"
    confirmed = client.post(
        "/api/strategies/confirm",
        json={"conversation_id": convo["id"], "turn_id": turn["id"]},
        headers=ORIGIN,
    )
    assert confirmed.status_code == 201, confirmed.text

    # Proof of ownership: a wrong signature fails, the right one holds.
    message = got["message"]
    wrong = client.post(
        f"/api/shadow/{iid}/verify",
        json={"signature": _sign(message + " ")},
        headers=ORIGIN,
    )
    assert wrong.json() == {"verified": False}
    right = client.post(
        f"/api/shadow/{iid}/verify", json={"signature": _sign(message)}, headers=ORIGIN
    )
    assert right.json() == {"verified": True}
    assert client.get("/api/shadow").json()["imports"][0]["verified"] is True

    # The import is the person's own: a teammate does not see it.
    mate = _email()
    client.post(
        "/api/team/invitations", json={"email": mate, "role": "editor"}, headers=ORIGIN
    )
    invitation = _invite_token(mailer, mate)
    other = _sign_in(client, mailer, mate)
    _as(client, other)
    joined = client.post(
        "/invite",
        data={"token": invitation},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert joined.status_code == 303
    assert client.get("/auth/me").json()["workspace"]["id"] == str(me.workspace)
    assert client.get(f"/api/shadow/{iid}").status_code == 404
    assert client.get("/api/shadow").json()["imports"] == []
    _as(client, cookie)
    assert client.delete(f"/api/shadow/{iid}", headers=ORIGIN).status_code == 204
    assert client.get("/api/shadow").json()["imports"] == []
