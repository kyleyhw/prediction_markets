"""Channels, the outbox, briefs, webhooks and the MCP server (plan, tasks
85 to 89; docs/collaboration.md).

Chat platforms are simulated: their callbacks are signed here exactly as
they document signing, and outgoing calls go to a recording stand-in for
the network, so nothing leaves the machine (the local stand-in for cloud
hosting, flag F16)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tests.test_platform_web import (  # noqa: F401 - fixtures
    APP_URL,
    ORIGIN,
    _as,
    _email,
    _sign_in,
    owner,
    pytestmark,
)
from vp.platform import briefs, channels, delivery, mcp_server
from vp.platform.config import Settings
from vp.platform.mail import OutboxMailer
from vp.platform.web import create_app

MASTER = base64.b64encode(os.urandom(32)).decode()


class Recorder:
    """The network, recorded: every call answers as its platform would, or
    fails while `failing` is set."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.failing = False

    def __call__(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.failing:
            raise ConnectionError("the receiver is down")
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"ok": True, "result": {"message_id": len(self.calls)}},
        )


@pytest.fixture(scope="module")
def mailer() -> OutboxMailer:
    return OutboxMailer()


@pytest.fixture(scope="module")
def keyed(
    owner,  # noqa: F811
    mailer: OutboxMailer,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[TestClient, Settings]]:
    settings = Settings(
        database_url=APP_URL,
        data_root=tmp_path_factory.mktemp("data"),
        public_url="http://testserver",
        master_key=MASTER,
    )
    app = create_app(settings, mailer=mailer, sign_in_limit=100_000)
    with TestClient(app) as test_client:
        yield test_client, settings


def _ctx(app_pool, settings: Settings, mailer: OutboxMailer) -> SimpleNamespace:
    return SimpleNamespace(
        pool=app_pool, services=SimpleNamespace(settings=settings, mailer=mailer)
    )


def _slack_headers(secret: str, body: bytes, stamp: int | None = None) -> dict:
    stamp = stamp or int(time.time())
    base = f"v0:{stamp}:".encode() + body
    return {
        "X-Slack-Request-Timestamp": str(stamp),
        "X-Slack-Signature": "v0="
        + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


def test_adapters_sign_and_verify_as_each_platform_documents() -> None:
    net = Recorder()
    sent = channels.WebhookAdapter(net).send(
        channels.Target("webhook", "https://hooks.test/x", "s3cret"), "hello", {"a": 1}
    )
    call = net.calls[-1]
    assert sent["status"] == 200
    assert call["headers"]["X-VP-Signature"] == channels.signature(
        "s3cret", call["data"]
    )
    channels.TelegramAdapter(net).send(
        channels.Target("telegram", "42", "123:ABC"), "hi", {"chat": "7"}
    )
    assert net.calls[-1]["url"].endswith("/bot123:ABC/sendMessage")
    assert net.calls[-1]["json"] == {"chat_id": "7", "text": "hi"}
    update = json.dumps(
        {
            "message": {
                "text": "/ask why?",
                "chat": {"id": 7, "type": "private"},
                "from": {"id": 9, "username": "ada"},
            }
        }
    ).encode()
    token = {
        "x-telegram-bot-api-secret-token": channels.telegram_webhook_secret("123:ABC")
    }
    message = channels.TelegramAdapter.inbound(token, update, "123:ABC")
    assert message == channels.Inbound("9", "7", "/ask why?", True, "ada")
    with pytest.raises(channels.Unverified):
        channels.TelegramAdapter.inbound(
            {"x-telegram-bot-api-secret-token": "wrong"}, update, "123:ABC"
        )
    body = json.dumps({"type": "url_verification", "challenge": "c1"}).encode()
    headers = {k.lower(): v for k, v in _slack_headers("sig", body).items()}
    assert channels.SlackAdapter.inbound(headers, body, "sig") == {"challenge": "c1"}
    with pytest.raises(channels.Unverified):  # replayed ten minutes later
        channels.SlackAdapter.inbound(headers, body, "sig", now=time.time() + 600)
    with pytest.raises(channels.Unverified):
        channels.SlackAdapter.inbound(headers, body, "another secret")


def test_the_outbox_retries_backs_off_and_gives_up_telling_the_owners(
    keyed,
    mailer: OutboxMailer,
    app_pool,
    owner,  # noqa: F811
) -> None:
    client, settings = keyed
    # Whatever other tests left in the outbox goes first.
    delivery.deliver(
        _ctx(app_pool, settings, mailer), channels.adapters(mailer, Recorder())
    )
    ada = _email()
    _as(client, _sign_in(client, mailer, ada))
    made = client.post(
        "/api/channels",
        json={
            "kind": "webhook",
            "name": "desk",
            "target": "https://hooks.test/desk",
            "secret": "desk-secret",  # pragma: allowlist secret
        },
        headers=ORIGIN,
    )
    assert made.status_code == 201, made.text
    channel = made.json()["id"]
    # The person routes fills to the channel; a fill notice is queued there.
    client.put(
        "/api/notifications/prefs",
        json={"kinds": {"fill": [f"channel:{channel}"]}},
        headers=ORIGIN,
    )
    from vp.platform import notify
    from vp.platform.auth import resolve_session
    from vp.platform.db import tenant_session

    with app_pool.connection() as conn:
        me = resolve_session(conn, client.cookies.get("vp_session") or "")
    assert me is not None
    with app_pool.connection() as conn, tenant_session(conn, me):
        notify.notify(conn, [me.user_id], "fill", "Bought 12 shares", "At 41 cents.")
    net = Recorder()
    ctx = _ctx(app_pool, settings, mailer)
    table = channels.adapters(mailer, net)
    assert delivery.deliver(ctx, table) == {"sent": 1, "retried": 0, "dead": 0}
    body = net.calls[-1]["data"]
    assert json.loads(body)["text"].startswith("Bought 12 shares")
    assert net.calls[-1]["headers"]["X-VP-Signature"] == channels.signature(
        "desk-secret", body
    )
    listed = client.get("/api/channels").json()
    assert listed[0]["sent"] == 1 and listed[0]["target"] == "hooks.test"
    # A receiver that is down: retried with growing gaps, then given up.
    with app_pool.connection() as conn, tenant_session(conn, me):
        notify.notify(conn, [me.user_id], "fill", "Sold 3 shares")
    net.failing = True
    later = datetime.now(tz=UTC)
    for attempt in range(5):
        with owner.transaction():
            owner.execute(
                "update outbox set next_attempt_at = now() where state = 'queued' "
                "and workspace_id = %s",
                (me.workspace,),
            )
        counts = delivery.deliver(ctx, table, now=later)
        assert counts == (
            {"sent": 0, "retried": 1, "dead": 0}
            if attempt < 4
            else {"sent": 0, "retried": 0, "dead": 1}
        )
    notices = client.get("/api/notifications").json()["items"]
    assert (
        notices[0]["kind"] == "delivery"
        and "could not be delivered" in notices[0]["title"]
    )
    assert client.get("/api/channels").json()[0]["dead"] == 1
    # Another failure within the hour is counted, not notified again.
    with owner.transaction():
        told = owner.execute(
            "select vp_notify_owners(%s, 'delivery', "
            "'A message could not be delivered', 'again')",
            (me.workspace,),
        ).fetchone()
    assert told == (0,)


def test_a_chat_pairs_on_the_page_then_asks_and_resets(
    keyed,
    mailer: OutboxMailer,
    owner,  # noqa: F811
) -> None:
    client, settings = keyed
    _as(client, _sign_in(client, mailer, _email()))
    made = client.post(
        "/api/channels",
        json={
            "kind": "telegram",
            "name": "team chat",
            "target": "-100123",
            "secret": "777:TOKEN",  # pragma: allowlist secret
        },
        headers=ORIGIN,
    )
    assert made.status_code == 201
    channel = made.json()["id"]
    secret = made.json()["telegram_secret_token"]
    cookie = client.cookies.get("vp_session")

    def say(text: str, chat_type: str = "private", token: str = secret) -> int:
        client.cookies.clear()
        update = {
            "message": {
                "text": text,
                "chat": {"id": 55, "type": chat_type},
                "from": {"id": 99, "username": "bob"},
            }
        }
        return client.post(
            f"/hooks/{channel}",
            content=json.dumps(update),
            headers={"X-Telegram-Bot-Api-Secret-Token": token},
        ).status_code

    def replies() -> list[str]:
        with owner.transaction():
            rows = owner.execute(
                "select payload ->> 'text' from outbox where channel_id = %s "
                "and kind = 'reply' order by created_at",
                (UUID(channel),),
            ).fetchall()
        return [r[0] for r in rows]

    assert say("hello", token="forged") == 401
    assert say("hello from a group", chat_type="group") == 200
    assert replies() == []  # an unknown voice in a group is ignored
    assert say("hello") == 200
    (pairing,) = replies()
    code = pairing.split("code ")[1].split()[0]
    assert say("/approve " + code) == 200
    assert "on the page" in replies()[-1]
    _as(client, cookie)
    pending = client.get("/api/channels").json()[0]["pairing"]
    assert {p["code"] for p in pending} >= {code}
    assert (
        client.post("/api/channels/pair", json={"code": code}, headers=ORIGIN).json()[
            "sender"
        ]
        == "99"
    )
    assert say("/ask what closes today?") == 200
    # No model key on this service: the chat is told, and nothing is queued.
    assert "no model key" in replies()[-1]
    assert say("/reset") == 200 and replies()[-1].startswith("Started a new")


def test_a_brief_is_proposed_confirmed_by_a_person_run_and_parsed(
    keyed,
    mailer: OutboxMailer,
    app_pool,
    owner,  # noqa: F811
) -> None:
    client, settings = keyed
    _as(client, _sign_in(client, mailer, _email()))
    with pytest.raises(ValueError, match="no variable"):
        briefs.check_variables("weekly", {"threshold": 5})
    with pytest.raises(ValueError, match="between"):
        briefs.check_variables("disagreements", {"threshold": 90})
    made = client.post(
        "/api/briefs",
        json={
            "template": "settlements",
            "variables": {"days": 2},
            "cron": "0 8 * * *",
            "timezone": "Europe/London",
        },
        headers=ORIGIN,
    )
    assert made.status_code == 201, made.text
    brief = made.json()["id"]
    listed = client.get("/api/briefs").json()["briefs"]
    assert listed[0]["enabled"] is False
    # A token (an agent) cannot switch it on; a person on the page can.
    token = client.post(
        "/api/tokens", json={"name": "agent", "scope": "write"}, headers=ORIGIN
    ).json()["token"]
    cookie = client.cookies.get("vp_session")
    client.cookies.clear()
    refused = client.post(
        f"/api/briefs/{brief}/confirm", headers={"Authorization": f"Bearer {token}"}
    )
    assert refused.status_code == 403
    _as(client, cookie)
    assert (
        client.post(f"/api/briefs/{brief}/confirm", headers=ORIGIN).status_code == 204
    )
    from vp.platform.auth import resolve_session

    with app_pool.connection() as conn:
        me = resolve_session(conn, cookie or "")
    (schedules,) = owner.execute(
        "select count(*) from schedules where name = %s", (f"brief {brief}",)
    ).fetchone()
    assert me is not None and schedules == 1
    job = SimpleNamespace(principal=me, payload={"brief_id": brief})
    ctx = SimpleNamespace(
        services=SimpleNamespace(pool=app_pool, refresh=lambda d: None), job=job
    )
    assert briefs.run(ctx)["rows"] == 0
    last = client.get("/api/briefs").json()["briefs"][0]["last"]
    assert last == {"template": "settlements", "date": last["date"], "rows": []}
    assert client.post(f"/api/briefs/{brief}/stop", headers=ORIGIN).status_code == 204


def test_webhooks_are_signed_with_their_own_secret(
    keyed, mailer: OutboxMailer, app_pool
) -> None:
    client, settings = keyed
    delivery.deliver(
        _ctx(app_pool, settings, mailer), channels.adapters(mailer, Recorder())
    )
    _as(client, _sign_in(client, mailer, _email()))
    made = client.post(
        "/api/webhooks",
        json={"url": "https://receiver.test/vp", "events": ["run.finished"]},
        headers=ORIGIN,
    )
    assert made.status_code == 201
    secret = made.json()["secret"]
    assert "secret" not in json.dumps(client.get("/api/webhooks").json()["hooks"])
    from vp.platform import webhooks
    from vp.platform.auth import resolve_session
    from vp.platform.db import tenant_session

    with app_pool.connection() as conn:
        me = resolve_session(conn, client.cookies.get("vp_session") or "")
    assert me is not None
    with app_pool.connection() as conn, tenant_session(conn, me):
        assert webhooks.emit(conn, "run.finished", {"run_id": "r1"}) == 1
        assert webhooks.emit(conn, "paper.settled", {"account_id": "a"}) == 0
    net = Recorder()
    delivery.deliver(_ctx(app_pool, settings, mailer), channels.adapters(mailer, net))
    call = net.calls[-1]
    assert call["url"] == "https://receiver.test/vp"
    assert json.loads(call["data"])["data"] == {"run_id": "r1"}
    assert call["headers"]["X-VP-Signature"] == channels.signature(secret, call["data"])


def test_the_mcp_server_is_read_only_and_needs_a_token(
    keyed, mailer: OutboxMailer
) -> None:
    client, _ = keyed
    assert set(mcp_server.TOOLS) == {
        "search_markets",
        "market_detail",
        "evidence",
        "forecasts",
        "run_cards",
        "paper_status",
        "signal_bench",
    }
    _as(client, _sign_in(client, mailer, _email()))
    token = client.post(
        "/api/tokens", json={"name": "agent", "scope": "read"}, headers=ORIGIN
    ).json()["token"]
    client.cookies.clear()
    headers = {
        "Accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2025-06-18",
    }
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert client.post("/mcp", json=rpc, headers=headers).status_code == 401
    headers["Authorization"] = f"Bearer {token}"
    listed = client.post("/mcp", json=rpc, headers=headers).json()["result"]["tools"]
    names = {t["name"] for t in listed}
    assert names == set(mcp_server.TOOLS)
    assert not names & {"place_order", "sign", "send", "trade", "order"}
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "paper_status", "arguments": {}},
    }
    answer = client.post("/mcp", json=call, headers=headers).json()["result"]
    assert answer["isError"] is False and json.loads(answer["content"][0]["text"]) == []


def test_quiet_hours_hold_a_notice_back(keyed, mailer: OutboxMailer, app_pool) -> None:
    client, _ = keyed
    _as(client, _sign_in(client, mailer, _email()))
    now = datetime.now(tz=UTC)
    start = (now - timedelta(hours=1)).strftime("%H:%M")
    end = (now + timedelta(hours=2)).strftime("%H:%M")
    client.put(
        "/api/notifications/prefs",
        json={"kinds": {}, "quiet": {"start": start, "end": end, "tz": "UTC"}},
        headers=ORIGIN,
    )
    from vp.platform import notify
    from vp.platform.auth import resolve_session
    from vp.platform.db import tenant_session

    with app_pool.connection() as conn:
        me = resolve_session(conn, client.cookies.get("vp_session") or "")
    assert me is not None
    with app_pool.connection() as conn, tenant_session(conn, me):
        notify.notify(conn, [me.user_id], "halt", "Trading halted")
        (due,) = conn.execute(
            "select next_attempt_at from outbox where kind = 'notification' "
            "order by created_at desc limit 1"
        ).fetchone()
    assert due > now + timedelta(minutes=100)  # held until the quiet hours end
