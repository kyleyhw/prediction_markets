"""Comments on runs, markets and strategies (plan, task 83;
docs/collaboration.md).

Threads are one level deep: a reply names its parent, and a reply to a
reply joins the same thread. A mention is ``@`` and a member's address's
local part. Each mention and each reply notifies the person. Authors
delete their own comments and may correct them for five minutes; owners
hide anyone's, which keeps the row (and who hid it) for the record.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool

from vp.platform import notify
from vp.platform.db import tenant_session
from vp.platform.principal import Principal
from vp.platform.teams import NotAllowed, record

SUBJECTS = ("run", "market", "strategy")
EDIT_WINDOW = timedelta(minutes=5)
_MENTION = re.compile(r"(?<![\w.])@([A-Za-z0-9._+-]{1,64})")


def mentioned(body: str, members: dict[str, UUID]) -> list[UUID]:
    """The members a body mentions, by their address's local part."""
    return [members[m.lower()] for m in _MENTION.findall(body) if m.lower() in members]


def _link(kind: str, subject_id: str) -> str:
    return {"run": "#backtests", "market": f"#market/{subject_id}"}.get(
        kind, f"#strategy/{subject_id}"
    )


def add(
    pool: ConnectionPool,
    principal: Principal,
    subject_kind: str,
    subject_id: str,
    body: str,
    parent: UUID | None = None,
) -> str:
    if subject_kind not in SUBJECTS:
        raise ValueError(f"comments are on {', '.join(SUBJECTS)}")
    body = body.strip()
    if not 1 <= len(body) <= 4000:
        raise ValueError("a comment is 1 to 4,000 characters")
    with pool.connection() as conn, tenant_session(conn, principal):
        notified: list[UUID] = []
        if parent is not None:
            row = conn.execute(
                "select coalesce(parent_id, id), user_id from comments where id = %s "
                "and subject_kind = %s and subject_id = %s",
                (parent, subject_kind, subject_id),
            ).fetchone()
            if row is None:
                raise LookupError("no such comment to reply to")
            parent, author = row
            if author and author != principal.user_id:
                notified.append(author)
        row = conn.execute(
            "insert into comments (subject_kind, subject_id, parent_id, body) "
            "values (%s, %s, %s, %s) returning id",
            (subject_kind, subject_id, parent, body),
        ).fetchone()
        assert row is not None
        (cid,) = row
        people = {
            email.split("@")[0].lower(): uid
            for uid, email in conn.execute(
                "select u.id, u.email from memberships m "
                "join users u on u.id = m.user_id "
                "where m.workspace_id = vp_current_workspace()"
            ).fetchall()
        }
        me = conn.execute(
            "select email from users where id = %s", (principal.user_id,)
        ).fetchone()
        who = me[0].split("@")[0] if me else "someone"
        link = _link(subject_kind, subject_id)
        mentions = [u for u in mentioned(body, people) if u != principal.user_id]
        notify.notify(conn, mentions, "mention", f"{who} mentioned you", body, link)
        replies = [u for u in notified if u not in mentions]
        notify.notify(conn, replies, "reply", f"{who} replied to you", body, link)
        record(conn, "commented", subject_kind, subject_id, {"comment": str(cid)})
    return str(cid)


def thread(
    pool: ConnectionPool, principal: Principal, subject_kind: str, subject_id: str
) -> list[dict[str, Any]]:
    """The subject's comments, oldest first, replies under their parent."""
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select c.id, c.parent_id, u.email, c.user_id, c.body, c.created_at, "
            "c.edited_at, c.deleted_at, c.hidden_at from comments c "
            "left join users u on u.id = c.user_id "
            "where c.subject_kind = %s and c.subject_id = %s order by c.created_at",
            (subject_kind, subject_id),
        ).fetchall()
    out: list[dict[str, Any]] = []
    by_id: dict[UUID, dict[str, Any]] = {}
    for cid, parent, email, uid, body, at, edited, deleted, hidden in rows:
        gone = "deleted" if deleted else "hidden" if hidden else None
        item = {
            "id": str(cid),
            "who": email.split("@")[0] if email else None,
            "mine": uid == principal.user_id,
            "body": None if gone else body,
            "removed": gone,
            "created_at": at.isoformat(),
            "edited": edited is not None,
            "replies": [],
        }
        by_id[cid] = item
        if parent and parent in by_id:
            by_id[parent]["replies"].append(item)
        else:
            out.append(item)
    return out


def edit(pool: ConnectionPool, principal: Principal, cid: UUID, body: str) -> None:
    body = body.strip()
    if not 1 <= len(body) <= 4000:
        raise ValueError("a comment is 1 to 4,000 characters")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update comments set body = %s, edited_at = now() where id = %s "
            "and user_id = %s and deleted_at is null and hidden_at is null "
            "and created_at > now() - %s returning id",
            (body, cid, principal.user_id, EDIT_WINDOW),
        ).fetchone()
    if row is None:
        raise NotAllowed("only your own comment, within five minutes")


def delete(pool: ConnectionPool, principal: Principal, cid: UUID) -> None:
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update comments set deleted_at = now() where id = %s and user_id = %s "
            "and deleted_at is null returning id",
            (cid, principal.user_id),
        ).fetchone()
    if row is None:
        raise NotAllowed("only your own comment")


def hide(pool: ConnectionPool, principal: Principal, cid: UUID) -> None:
    """An owner hides a comment; the row stays, with who hid it."""
    if not principal.may_administer:
        raise NotAllowed("only an owner may hide comments")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update comments set hidden_at = now(), hidden_by = %s where id = %s "
            "and hidden_at is null returning subject_kind, subject_id",
            (principal.user_id, cid),
        ).fetchone()
        if row is None:
            raise LookupError("no such comment")
        record(conn, "comment_hidden", row[0], row[1], {"comment": str(cid)})
