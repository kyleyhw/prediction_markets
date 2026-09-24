"""Teams: invitations, members, roles and the activity feed (plan, task 81;
docs/collaboration.md).

A team is a workspace with more than one member. Owners invite by email;
the invited person accepts after signing in with that address, through
`vp_accept_invitation`, which is the only path into another workspace.
Every change here, and every change elsewhere that a teammate should see,
is recorded with `record` in the workspace's activity feed.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.principal import Principal

ROLES = ("owner", "editor", "viewer")


class NotAllowed(PermissionError):
    """The principal's role does not permit this change."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def record(
    conn: psycopg.Connection,
    action: str,
    subject_kind: str | None = None,
    subject_id: object = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append to the workspace's activity feed, as the session's person."""
    conn.execute(
        "insert into activity (action, subject_kind, subject_id, detail) "
        "values (%s, %s, %s, %s)",
        (
            action,
            subject_kind,
            None if subject_id is None else str(subject_id),
            Jsonb(detail or {}),
        ),
    )


@contextmanager
def _owner_kept() -> Iterator[None]:
    """Turn the database's refusal to leave a team ownerless into a ValueError."""
    try:
        yield
    except psycopg.errors.RaiseException as exc:
        if "at least one owner" in str(exc):
            raise ValueError(
                "a team keeps at least one owner: make someone else an owner first"
            ) from None
        raise


def _owner(principal: Principal) -> None:
    if not principal.may_administer:
        raise NotAllowed("only an owner may change the team")


def members(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select m.user_id, u.email, m.role, m.created_at from memberships m "
            "join users u on u.id = m.user_id "
            "where m.workspace_id = vp_current_workspace() order by m.created_at"
        ).fetchall()
    return [
        {
            "user_id": str(uid),
            "email": email,
            "role": role,
            "joined_at": at.isoformat(),
            "you": uid == principal.user_id,
        }
        for uid, email, role, at in rows
    ]


def invite(
    pool: ConnectionPool, principal: Principal, email: str, role: str
) -> tuple[str, str]:
    """Invite an address; returns (invitation id, the token for its link)."""
    _owner(principal)
    email = email.strip().lower()
    if role not in ("editor", "viewer") or "@" not in email[1:]:
        raise ValueError("invite an address as an editor or a viewer")
    token = secrets.token_urlsafe(32)
    with pool.connection() as conn, tenant_session(conn, principal):
        if conn.execute(
            "select 1 from memberships m join users u on u.id = m.user_id "
            "where m.workspace_id = vp_current_workspace() and lower(u.email) = %s",
            (email,),
        ).fetchone():
            raise ValueError("that person is already a member")
        conn.execute(
            "update invitations set revoked_at = now() where lower(email) = %s "
            "and accepted_at is null and revoked_at is null",
            (email,),
        )
        row = conn.execute(
            "insert into invitations (email, role, token_hash, invited_by) "
            "values (%s, %s, %s, %s) returning id",
            (email, role, _hash(token), principal.user_id),
        ).fetchone()
        assert row is not None
        (inv_id,) = row
        record(conn, "invited", "member", email, {"role": role})
    return str(inv_id), token


def invitations(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select id, email, role, created_at, expires_at from invitations "
            "where accepted_at is null and revoked_at is null and expires_at > now() "
            "order by created_at desc"
        ).fetchall()
    return [
        {
            "id": str(i),
            "email": e,
            "role": r,
            "created_at": c.isoformat(),
            "expires_at": x.isoformat(),
        }
        for i, e, r, c, x in rows
    ]


def revoke_invitation(pool: ConnectionPool, principal: Principal, inv: UUID) -> bool:
    _owner(principal)
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update invitations set revoked_at = now() where id = %s "
            "and accepted_at is null and revoked_at is null returning email",
            (inv,),
        ).fetchone()
        if row:
            record(conn, "invitation_revoked", "member", row[0])
    return row is not None


def accept(pool: ConnectionPool, session_token: str, token: str) -> UUID | None:
    """Accept an invitation for the signed-in person; the workspace joined.

    The session now acts in that workspace, and the feed records the join.
    """
    from vp.platform.auth import resolve_session

    with pool.connection() as conn:
        row = conn.execute(
            "select vp_accept_invitation(%s, %s)",
            (_hash(token), _hash(session_token)),
        ).fetchone()
        ws = row[0] if row else None
        joined = resolve_session(conn, session_token) if ws else None
    if joined is not None:
        with pool.connection() as conn, tenant_session(conn, joined):
            record(
                conn, "joined", "member", joined.user_id, {"role": sorted(joined.roles)}
            )
    return ws


def set_role(
    pool: ConnectionPool, principal: Principal, user_id: UUID, role: str
) -> None:
    _owner(principal)
    if role not in ROLES:
        raise ValueError(f"a role is one of {', '.join(ROLES)}")
    with _owner_kept(), pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update memberships set role = %s where workspace_id = "
            "vp_current_workspace() and user_id = %s returning user_id",
            (role, user_id),
        ).fetchone()
        if row is None:
            raise LookupError("no such member")
        record(conn, "role_changed", "member", user_id, {"role": role})


def remove(pool: ConnectionPool, principal: Principal, user_id: UUID) -> None:
    """Remove a member (an owner), or leave (anyone, removing themselves)."""
    if user_id != principal.user_id:
        _owner(principal)
    with _owner_kept(), pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "delete from memberships where workspace_id = vp_current_workspace() "
            "and user_id = %s returning user_id",
            (user_id,),
        ).fetchone()
        if row is None:
            raise LookupError("no such member")
        record(
            conn,
            "left" if user_id == principal.user_id else "removed",
            "member",
            user_id,
        )


def workspaces(pool: ConnectionPool, session_token: str) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        rows = conn.execute(
            "select * from vp_my_workspaces(%s)", (_hash(session_token),)
        ).fetchall()
    return [{"id": str(w), "name": n, "role": r, "members": m} for w, n, r, m in rows]


def switch(pool: ConnectionPool, session_token: str, workspace: UUID) -> bool:
    with pool.connection() as conn:
        (ok,) = conn.execute(
            "select vp_switch_workspace(%s, %s)", (_hash(session_token), workspace)
        ).fetchone() or (False,)
    return bool(ok)


def rename(pool: ConnectionPool, principal: Principal, name: str) -> None:
    _owner(principal)
    name = name.strip()
    if not 1 <= len(name) <= 100:
        raise ValueError("a name is 1 to 100 characters")
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "update workspaces set name = %s where id = vp_current_workspace()",
            (name,),
        )
        record(conn, "renamed", "workspace", None, {"name": name})


def activity(
    pool: ConnectionPool, principal: Principal, limit: int = 100
) -> list[dict[str, Any]]:
    """The workspace's feed, newest first, each change with who made it."""
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select a.at, u.email, a.action, a.subject_kind, a.subject_id, a.detail "
            "from activity a left join users u on u.id = a.user_id "
            "order by a.at desc, a.id desc limit %s",
            (min(max(limit, 1), 500),),
        ).fetchall()
    return [
        {
            "at": at.isoformat(),
            "who": email,
            "action": action,
            "subject_kind": kind,
            "subject_id": sid,
            "detail": detail,
        }
        for at, email, action, kind, sid, detail in rows
    ]
