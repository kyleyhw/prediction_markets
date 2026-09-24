"""Notifications: each person's notices and how they want them delivered
(plan, task 87; docs/collaboration.md).

A notice is always kept in the app. It is also sent by email, or to one of
the workspace's channels, when the person's preferences say so for its
kind. Quiet hours move the first delivery attempt to the end of the quiet
period; they never drop a notice. Delivery itself is the outbox's job
(`vp.platform.delivery`).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.principal import Principal

KINDS = (
    "mention",
    "reply",
    "invitation",
    "fill",
    "settlement",
    "budget",
    "halt",
    "brief",
    "health",
    "delivery",
)
# What a person gets by email until they choose otherwise: the notices a
# person would want to hear about while away from the page.
EMAIL_BY_DEFAULT = frozenset({"mention", "invitation", "halt", "budget", "health"})


def _clock(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def quiet_until(prefs: dict[str, Any], now: datetime) -> datetime | None:
    """The end of the quiet period ``now`` falls in, or None if it does not."""
    quiet = prefs.get("quiet") or {}
    if not quiet.get("start") or not quiet.get("end"):
        return None
    zone = ZoneInfo(quiet.get("tz") or "UTC")
    local = now.astimezone(zone)
    start, end = _clock(quiet["start"]), _clock(quiet["end"])
    t = local.time()
    inside = (start <= t < end) if start < end else (t >= start or t < end)
    if not inside:
        return None
    ends = datetime.combine(local.date(), end, tzinfo=zone)
    if ends <= local:
        ends += timedelta(days=1)
    return ends.astimezone(UTC)


def routes(prefs: dict[str, Any], kind: str) -> list[str]:
    """Where a notice of ``kind`` goes besides the app: "email", "channel:<id>"."""
    chosen = (prefs.get("kinds") or {}).get(kind)
    if chosen is None:
        return ["email"] if kind in EMAIL_BY_DEFAULT else []
    return [r for r in chosen if r == "email" or r.startswith("channel:")]


def notify(
    conn: psycopg.Connection,
    user_ids: list[UUID],
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    now: datetime | None = None,
) -> int:
    """Notify members of the session's workspace; returns how many."""
    now = now or datetime.now(tz=UTC)
    sent = 0
    for uid in dict.fromkeys(user_ids):
        conn.execute(
            "insert into notifications (user_id, kind, title, body, link) "
            "values (%s, %s, %s, %s, %s)",
            (uid, kind, title[:200], body[:2000], link),
        )
        row = conn.execute(
            "select coalesce(p.prefs, '{}'::jsonb), u.email from users u "
            "left join notification_prefs p on p.user_id = u.id "
            "and p.workspace_id = vp_current_workspace() where u.id = %s",
            (uid,),
        ).fetchone()
        prefs, email = row if row else ({}, None)
        start = quiet_until(prefs, now) or now
        for route in routes(prefs, kind):
            payload = {"subject": title, "text": f"{title}\n\n{body}".strip()}
            if link:
                payload["link"] = link
            if route == "email" and email:
                conn.execute(
                    "insert into outbox (address, kind, payload, next_attempt_at) "
                    "values (%s, 'notification', %s, %s)",
                    (email, Jsonb(payload), start),
                )
            elif route.startswith("channel:"):
                conn.execute(
                    "insert into outbox (channel_id, kind, payload, next_attempt_at) "
                    "select id, 'notification', %s, %s from channels "
                    "where id = %s and disabled_at is null",
                    (Jsonb(payload), start, route.removeprefix("channel:")),
                )
        sent += 1
    return sent


def members(conn: psycopg.Connection, roles: tuple[str, ...] = ()) -> list[UUID]:
    """The workspace's members, or those holding one of ``roles``."""
    rows = conn.execute(
        "select user_id from memberships where workspace_id = vp_current_workspace()"
        + (" and role = any(%s)" if roles else ""),
        ((list(roles),) if roles else ()),
    ).fetchall()
    return [r[0] for r in rows]


def listing(
    pool: ConnectionPool, principal: Principal, limit: int = 50
) -> dict[str, Any]:
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select id, kind, title, body, link, created_at, read_at "
            "from notifications order by created_at desc limit %s",
            (min(max(limit, 1), 200),),
        ).fetchall()
        (unread,) = conn.execute(
            "select count(*) from notifications where read_at is null"
        ).fetchone() or (0,)
    return {
        "unread": unread,
        "items": [
            {
                "id": str(i),
                "kind": k,
                "title": t,
                "body": b,
                "link": link,
                "created_at": c.isoformat(),
                "read": r is not None,
            }
            for i, k, t, b, link, c, r in rows
        ],
    }


def mark_read(pool: ConnectionPool, principal: Principal, ids: list[UUID]) -> int:
    with pool.connection() as conn, tenant_session(conn, principal):
        cur = conn.execute(
            "update notifications set read_at = now() where read_at is null"
            + (" and id = any(%s)" if ids else ""),
            ((ids,) if ids else ()),
        )
    return cur.rowcount


def get_prefs(pool: ConnectionPool, principal: Principal) -> dict[str, Any]:
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select prefs from notification_prefs where user_id = vp_current_user_id()"
        ).fetchone()
    prefs = row[0] if row else {}
    return {
        "kinds": {k: routes(prefs, k) for k in KINDS},
        "quiet": prefs.get("quiet") or {},
    }


def set_prefs(
    pool: ConnectionPool, principal: Principal, prefs: dict[str, Any]
) -> dict[str, Any]:
    kinds = prefs.get("kinds") or {}
    unknown = set(kinds) - set(KINDS)
    if unknown:
        raise ValueError(f"unknown notice kinds: {', '.join(sorted(unknown))}")
    quiet = prefs.get("quiet") or {}
    if quiet:
        ZoneInfo(quiet.get("tz") or "UTC")  # raises on an unknown zone
        _clock(quiet["start"]), _clock(quiet["end"])
    clean = {"kinds": {k: routes({"kinds": kinds}, k) for k in kinds}, "quiet": quiet}
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "insert into notification_prefs (prefs) values (%s) "
            "on conflict (user_id, workspace_id) do update set prefs = excluded.prefs, "
            "updated_at = now()",
            (Jsonb(clean),),
        )
    return get_prefs(pool, principal)
