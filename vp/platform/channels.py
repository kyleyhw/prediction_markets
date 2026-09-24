"""Channels: where research and notices reach people, and where a chat can
ask questions (plan, task 85; docs/collaboration.md).

An adapter sends a message to an opaque target and, where the platform
calls us, turns a verified inbound request into a message. Each adapter
checks the platform's own signature scheme before reading anything. A
known, paired sender's text is a command (`/reset`, `/ask <question>`);
an unknown sender in a direct chat is answered with a pairing code, which
an owner approves on the page, never in the chat.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import string
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import psycopg
import requests
from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.llmops import seal, unseal
from vp.platform.mail import Mailer, Message
from vp.platform.principal import Principal
from vp.platform.teams import NotAllowed, record

KINDS = ("email", "webhook", "telegram", "slack", "discord")
# The kinds whose sending needs a secret stored with the channel.
SECRET_KINDS = {
    "webhook": "signing secret",
    "telegram": "bot token",
    "slack": "signing secret",
}
SLACK_SKEW = 300  # seconds a Slack request's timestamp may be off
PAIRING_ALPHABET = string.ascii_uppercase + string.digits

Post = Callable[..., Any]


class Unverified(PermissionError):
    """An inbound request whose signature does not check out."""


class CannotAsk(RuntimeError):
    """A question cannot be queued (no model key, or over budget); the
    message is posted in the chat as the reply."""


@dataclass(frozen=True)
class Inbound:
    """One message from a chat: who, in which chat, what they said."""

    sender: str
    chat: str
    text: str
    direct: bool
    display: str = ""


@dataclass(frozen=True)
class Target:
    """Where one outgoing message goes: a channel's kind, target and secret."""

    kind: str
    target: str
    secret: str | None = None


class Adapter(Protocol):
    def send(self, target: Target, text: str, data: dict[str, Any]) -> dict[str, Any]:
        """Deliver, returning the provider's receipt; raise on failure."""
        ...


def signature(secret: str, body: bytes) -> str:
    """The header value the generic webhook carries: sha256=<hex HMAC>."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class EmailAdapter:
    def __init__(self, mailer: Mailer) -> None:
        self.mailer = mailer

    def send(self, target: Target, text: str, data: dict[str, Any]) -> dict[str, Any]:
        subject = str(data.get("subject") or text.splitlines()[0])[:150]
        link = data.get("link")
        self.mailer.send(
            Message(
                to=target.target,
                subject=subject,
                body=text + (f"\n\n{link}" if link else ""),
            )
        )
        return {"provider": "email", "to": target.target}


class WebhookAdapter:
    def __init__(self, post: Post = requests.post) -> None:
        self.post = post

    def send(self, target: Target, text: str, data: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"text": text, **data}, sort_keys=True).encode()
        headers = {"Content-Type": "application/json"}
        if target.secret:
            headers["X-VP-Signature"] = signature(target.secret, body)
        response = self.post(target.target, data=body, headers=headers, timeout=15)
        response.raise_for_status()
        return {"provider": "webhook", "status": response.status_code}


class TelegramAdapter:
    """Bot API `sendMessage`; inbound updates carry the webhook's secret token."""

    def __init__(self, post: Post = requests.post) -> None:
        self.post = post

    def send(self, target: Target, text: str, data: dict[str, Any]) -> dict[str, Any]:
        if not target.secret:
            raise ValueError("a Telegram channel needs its bot token")
        chat = data.get("chat") or target.target
        response = self.post(
            f"https://api.telegram.org/bot{target.secret}/sendMessage",
            json={"chat_id": chat, "text": text[:4096]},
            timeout=15,
        )
        response.raise_for_status()
        result = response.json().get("result") or {}
        return {"provider": "telegram", "message_id": result.get("message_id")}

    @staticmethod
    def inbound(headers: dict[str, str], body: bytes, secret: str) -> Inbound | None:
        sent = headers.get("x-telegram-bot-api-secret-token", "")
        if not hmac.compare_digest(sent, hashlib.sha256(secret.encode()).hexdigest()):
            raise Unverified("the Telegram secret token does not match")
        message = (json.loads(body) or {}).get("message") or {}
        text, chat, sender = (
            message.get("text"),
            message.get("chat") or {},
            message.get("from") or {},
        )
        if not text or "id" not in chat or "id" not in sender:
            return None
        return Inbound(
            sender=str(sender["id"]),
            chat=str(chat["id"]),
            text=text,
            direct=chat.get("type") == "private",
            display=sender.get("username") or sender.get("first_name") or "",
        )


def telegram_webhook_secret(bot_token: str) -> str:
    """The secret_token to register with Telegram's setWebhook for a bot:
    derived from the bot token so nothing more needs storing."""
    return hashlib.sha256(bot_token.encode()).hexdigest()


class SlackAdapter:
    """An incoming-webhook URL out; the Events API in, signed v0."""

    def __init__(self, post: Post = requests.post) -> None:
        self.post = post

    def send(self, target: Target, text: str, data: dict[str, Any]) -> dict[str, Any]:
        response = self.post(target.target, json={"text": text[:3000]}, timeout=15)
        response.raise_for_status()
        return {"provider": "slack", "status": response.status_code}

    @staticmethod
    def inbound(
        headers: dict[str, str], body: bytes, secret: str, now: float | None = None
    ) -> Inbound | dict[str, Any] | None:
        stamp = headers.get("x-slack-request-timestamp", "")
        if not stamp.isdigit() or abs((now or time.time()) - int(stamp)) > SLACK_SKEW:
            raise Unverified("the Slack request is too old or unstamped")
        base = f"v0:{stamp}:".encode() + body
        expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(headers.get("x-slack-signature", ""), expected):
            raise Unverified("the Slack signature does not match")
        payload = json.loads(body)
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}
        event = payload.get("event") or {}
        if (
            event.get("type") != "message"
            or event.get("bot_id")
            or not event.get("text")
        ):
            return None
        return Inbound(
            sender=str(event.get("user")),
            chat=str(event.get("channel")),
            text=event["text"],
            direct=event.get("channel_type") == "im",
        )


class DiscordAdapter:
    def __init__(self, post: Post = requests.post) -> None:
        self.post = post

    def send(self, target: Target, text: str, data: dict[str, Any]) -> dict[str, Any]:
        response = self.post(target.target, json={"content": text[:2000]}, timeout=15)
        response.raise_for_status()
        return {"provider": "discord", "status": response.status_code}


def adapters(mailer: Mailer, post: Post = requests.post) -> dict[str, Adapter]:
    return {
        "email": EmailAdapter(mailer),
        "webhook": WebhookAdapter(post),
        "telegram": TelegramAdapter(post),
        "slack": SlackAdapter(post),
        "discord": DiscordAdapter(post),
    }


# ------------------------------------------------------------------ storage


def create(
    pool: ConnectionPool,
    principal: Principal,
    kind: str,
    name: str,
    target: str,
    secret: str | None,
    master_key: str | None,
) -> str:
    if not principal.may_administer:
        raise NotAllowed("only an owner may add a channel")
    if kind not in KINDS:
        raise ValueError(f"a channel is one of {', '.join(KINDS)}")
    if kind in ("webhook", "slack", "discord") and not target.startswith("https://"):
        raise ValueError("that channel needs an https URL")
    if kind == "telegram" and not secret:
        raise ValueError("a Telegram channel needs its bot token")
    sealed = seal(secret, master_key) if secret else (None, None)
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "insert into channels (kind, name, target, ciphertext, wrapped_key) "
            "values (%s, %s, %s, %s, %s) returning id",
            (kind, name.strip(), target.strip(), sealed[0], sealed[1]),
        ).fetchone()
        assert row is not None
        record(conn, "channel_added", "channel", row[0], {"kind": kind, "name": name})
    return str(row[0])


def listing(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select c.id, c.kind, c.name, c.target, c.ciphertext is not null, "
            "c.created_at, c.disabled_at, "
            "(select count(*) from channel_senders s where s.channel_id = c.id), "
            "(select count(*) from outbox o where o.channel_id = c.id "
            "and o.state = 'sent'), "
            "(select count(*) from outbox o where o.channel_id = c.id "
            "and o.state = 'dead') "
            "from channels c order by c.created_at"
        ).fetchall()
        codes = conn.execute(
            "select code, channel_id, display, sender_ref, created_at "
            "from pairing_codes "
            "where approved_at is null and expires_at > now() order by created_at"
        ).fetchall()
    pending: dict[UUID, list[dict[str, Any]]] = {}
    for code, cid, display, sender, at in codes:
        pending.setdefault(cid, []).append(
            {"code": code, "display": display, "sender": sender, "at": at.isoformat()}
        )
    return [
        {
            "id": str(cid),
            "kind": kind,
            "name": name,
            # An address or a chat id is shown; a URL with a secret path is not.
            "target": target if kind in ("email", "telegram") else target.split("/")[2],
            "has_secret": has_secret,
            "created_at": at.isoformat(),
            "disabled": disabled is not None,
            "senders": senders,
            "sent": sent,
            "dead": dead,
            "pairing": pending.get(cid, []),
        }
        for (
            cid,
            kind,
            name,
            target,
            has_secret,
            at,
            disabled,
            senders,
            sent,
            dead,
        ) in (rows)
    ]


def disable(pool: ConnectionPool, principal: Principal, channel: UUID) -> bool:
    if not principal.may_administer:
        raise NotAllowed("only an owner may remove a channel")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update channels set disabled_at = now() where id = %s "
            "and disabled_at is null returning name",
            (channel,),
        ).fetchone()
        if row:
            record(conn, "channel_removed", "channel", channel, {"name": row[0]})
    return row is not None


def approve(pool: ConnectionPool, principal: Principal, code: str) -> dict[str, Any]:
    """An owner approves a pairing code shown to a new sender in a chat."""
    if not principal.may_administer:
        raise NotAllowed("only an owner may approve a sender")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update pairing_codes set approved_at = now() where code = %s "
            "and approved_at is null and expires_at > now() "
            "returning channel_id, sender_ref, display",
            (code.strip().upper(),),
        ).fetchone()
        if row is None:
            raise LookupError("no such code, or it has expired")
        channel, sender, display = row
        conn.execute(
            "insert into channel_senders (channel_id, sender_ref, display, "
            "approved_by) "
            "values (%s, %s, %s, %s) on conflict do nothing",
            (channel, sender, display, principal.user_id),
        )
        record(conn, "sender_paired", "channel", channel, {"sender": display or sender})
    return {"channel_id": str(channel), "sender": sender}


# ------------------------------------------------------------------ inbound


@dataclass(frozen=True)
class Hook:
    """What an inbound webhook's channel is, found before any session."""

    workspace: UUID
    kind: str
    target: str
    secret: str | None
    created_by: UUID | None


def find_hook(
    pool: ConnectionPool, channel: UUID, master_key: str | None
) -> Hook | None:
    with pool.connection() as conn:
        row = conn.execute(
            "select * from vp_channel_for_hook(%s)", (channel,)
        ).fetchone()
    if row is None:
        return None
    ws, kind, target, ciphertext, wrapped, created_by = row
    secret = (
        unseal(bytes(ciphertext), bytes(wrapped), master_key) if ciphertext else None
    )
    return Hook(ws, kind, target, secret, created_by)


def _pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))


def handle(
    conn: psycopg.Connection,
    channel: UUID,
    message: Inbound,
    ask: Callable[[UUID | None, str], UUID],
) -> str | None:
    """Act on one verified message in the channel's tenant session.

    Returns the reply to post in the chat, or None to stay silent. ``ask``
    queues a read-only research turn in a conversation and returns the
    conversation's id.
    """
    paired = conn.execute(
        "select 1 from channel_senders where channel_id = %s and sender_ref = %s",
        (channel, message.sender),
    ).fetchone()
    if paired is None:
        if not message.direct:
            return None  # an unknown voice in a group is ignored
        if message.text.strip().lower().startswith(("/pair", "/approve")):
            return "Pairing is approved by a workspace owner on the page, not here."
        code = _pairing_code()
        conn.execute(
            "insert into pairing_codes (code, channel_id, workspace_id, sender_ref, "
            "display) "
            "values (%s, %s, vp_current_workspace(), %s, %s)",
            (code, channel, message.sender, message.display),
        )
        return (
            f"This chat is not paired yet. Ask a workspace owner to approve code "
            f"{code} under Settings → Channels. It is valid for an hour."
        )
    text = message.text.strip()
    if text == "/reset":
        conn.execute(
            "delete from chat_sessions where channel_id = %s and chat_ref = %s",
            (channel, message.chat),
        )
        return "Started a new conversation for this chat."
    if text.startswith("/ask"):
        question = text.removeprefix("/ask").strip()
        if not question:
            return "Ask a question after /ask."
        row = conn.execute(
            "select conversation_id from chat_sessions where channel_id = %s "
            "and chat_ref = %s",
            (channel, message.chat),
        ).fetchone()
        try:
            convo = ask(row[0] if row else None, question)
        except CannotAsk as exc:
            return str(exc)
        conn.execute(
            "insert into chat_sessions (channel_id, workspace_id, chat_ref, "
            "conversation_id) values (%s, vp_current_workspace(), %s, %s) "
            "on conflict (channel_id, chat_ref) do update set "
            "conversation_id = excluded.conversation_id, updated_at = now()",
            (channel, message.chat, convo),
        )
        return "Looking into it; the answer will be posted here."
    if message.direct:
        return "Commands: /ask <question>, /reset."
    return None
