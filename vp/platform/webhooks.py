"""Outgoing webhooks for technical users (plan, task 89;
docs/collaboration.md).

A workspace subscribes a URL to event kinds. Each hook has its own signing
secret, generated here and shown once; every delivery carries
``X-VP-Signature: sha256=<HMAC of the body>`` so the receiver can check it
came from us. Events go through the outbox, with its retries and receipts.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.llmops import seal
from vp.platform.principal import Principal
from vp.platform.teams import NotAllowed, record

EVENTS = ("run.finished", "paper.settled", "brief.delivered", "strategy.health")


def create(
    pool: ConnectionPool,
    principal: Principal,
    url: str,
    events: list[str],
    master_key: str | None,
) -> dict[str, str]:
    """Subscribe a URL; returns its id and its secret, which is not shown again."""
    if not principal.may_administer:
        raise NotAllowed("only an owner may add a webhook")
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
        raise ValueError("a webhook needs an https URL")
    unknown = set(events) - set(EVENTS)
    if unknown or not events:
        raise ValueError(f"events are some of {', '.join(EVENTS)}")
    secret = "whsec_" + secrets.token_urlsafe(24)  # pragma: allowlist secret
    ciphertext, wrapped = seal(secret, master_key)
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "insert into webhooks (url, events, ciphertext, wrapped_key) "
            "values (%s, %s, %s, %s) returning id",
            (url, sorted(set(events)), ciphertext, wrapped),
        ).fetchone()
        assert row is not None
        record(conn, "webhook_added", "webhook", row[0], {"events": sorted(events)})
    return {"id": str(row[0]), "secret": secret}


def listing(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select w.id, w.url, w.events, w.created_at, "
            "(select count(*) from outbox o where o.webhook_id = w.id "
            " and o.state = 'sent'), "
            "(select count(*) from outbox o where o.webhook_id = w.id "
            " and o.state = 'dead') "
            "from webhooks w where w.disabled_at is null order by w.created_at"
        ).fetchall()
    return [
        {
            "id": str(i),
            "host": url.split("/")[2],
            "events": list(events),
            "created_at": at.isoformat(),
            "sent": sent,
            "dead": dead,
        }
        for i, url, events, at, sent, dead in rows
    ]


def remove(pool: ConnectionPool, principal: Principal, hook: UUID) -> bool:
    if not principal.may_administer:
        raise NotAllowed("only an owner may remove a webhook")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update webhooks set disabled_at = now() where id = %s "
            "and disabled_at is null returning id",
            (hook,),
        ).fetchone()
        if row:
            record(conn, "webhook_removed", "webhook", hook)
    return row is not None


def emit(conn: psycopg.Connection, event: str, data: dict[str, Any]) -> int:
    """Queue the event for every hook of the session's workspace that wants it."""
    if event not in EVENTS:
        raise ValueError(f"not an event: {event}")
    payload = {
        "event": event,
        "data": data,
        "at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }
    cur = conn.execute(
        "insert into outbox (webhook_id, kind, payload) "
        "select id, 'webhook', %s from webhooks "
        "where disabled_at is null and %s = any(events)",
        (Jsonb({"text": event, **payload}), event),
    )
    return cur.rowcount
