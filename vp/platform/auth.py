"""Sign-in, sessions and API tokens.

Every secret here (the token in a sign-in link, the session cookie, an API
token) is 256 bits from the operating system's generator, handed to the
user once, and stored only as its SHA-256. The database functions of
migration 0002 do the work that crosses the tenancy boundary; this module
only generates secrets, hashes them, and turns what the functions return
into a `Principal`.

A plain hash rather than a slow password hash is correct here: these are
random 256-bit values, not passwords a person chose, so there is nothing
to brute-force and nothing a work factor would protect.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg

from vp.platform.principal import AuthMethod, Principal, Role

#: Name of the session cookie.
SESSION_COOKIE = "vp_session"

#: How long a session lasts. Fixed by migration 0002; the cookie matches it.
SESSION_SECONDS = 30 * 24 * 3600

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def new_secret() -> str:
    """A fresh 256-bit secret, URL-safe."""
    return secrets.token_urlsafe(32)


def digest(secret: str) -> str:
    """The stored form of a secret."""
    return hashlib.sha256(secret.encode()).hexdigest()


def normalize_email(raw: str) -> str | None:
    """Lower-cased and trimmed, or None if it cannot be an address."""
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        return None
    # The reserved `.invalid` domain (RFC 2606) delivers nowhere; the
    # platform's own user lives there, and nobody may sign in as it.
    if email.endswith(".invalid"):
        return None
    return email


def request_sign_in(conn: psycopg.Connection, email: str) -> str | None:
    """Record a sign-in token for an address.

    Args:
        conn: a connection as `vp_app`.
        email: a normalized address.

    Returns:
        The token to put in the link, or None when the address is over its
        rate limit. The caller must answer the person the same way in both
        cases, so the response reveals nothing about the address.
    """
    token = new_secret()
    row = conn.execute(
        "select vp_auth_request_sign_in(%s, %s)", (email, digest(token))
    ).fetchone()
    return token if row and row[0] else None


@dataclass(frozen=True)
class SignedIn:
    """The outcome of a successful sign-in."""

    session: str
    user_id: UUID
    workspace_id: UUID


def sign_in(conn: psycopg.Connection, token: str) -> SignedIn | None:
    """Exchange a sign-in token for a new session.

    Returns:
        The session secret to set as a cookie, or None when the token is
        unknown, already used or expired.
    """
    session = new_secret()
    row = conn.execute(
        "select user_id, workspace_id from vp_auth_sign_in(%s, %s)",
        (digest(token), digest(session)),
    ).fetchone()
    if row is None:
        return None
    return SignedIn(session=session, user_id=row[0], workspace_id=row[1])


def resolve_session(conn: psycopg.Connection, session: str) -> Principal | None:
    """The principal a session cookie belongs to, or None if it is not live."""
    row = conn.execute(
        "select user_id, workspace_id, role from vp_auth_resolve_session(%s)",
        (digest(session),),
    ).fetchone()
    if row is None:
        return None
    return Principal(
        subject=str(row[0]),
        auth_method=AuthMethod.SESSION,
        workspace=row[1],
        roles=frozenset({Role(row[2])}),
    )


def end_session(conn: psycopg.Connection, session: str) -> None:
    """Revoke a session. Unknown or already-revoked sessions are ignored."""
    conn.execute("select vp_auth_end_session(%s)", (digest(session),))


def resolve_api_token(conn: psycopg.Connection, token: str) -> Principal | None:
    """The principal an API token belongs to, or None if it is not live.

    A read-scoped token acts as a viewer whatever its owner's role; a
    write-scoped token acts with its owner's role, and never more.
    """
    row = conn.execute(
        "select user_id, workspace_id, role, scope from vp_auth_resolve_token(%s)",
        (digest(token),),
    ).fetchone()
    if row is None:
        return None
    role = Role(row[2]) if row[3] == "write" else Role.VIEWER
    return Principal(
        subject=str(row[0]),
        auth_method=AuthMethod.API_TOKEN,
        workspace=row[1],
        roles=frozenset({role}),
    )


@dataclass(frozen=True)
class ApiToken:
    """An API token as listed: never the secret."""

    id: UUID
    name: str
    scope: str
    created_at: datetime
    revoked_at: datetime | None


def create_api_token(
    conn: psycopg.Connection, principal: Principal, name: str, scope: str
) -> tuple[str, ApiToken]:
    """Create a token for the principal in its workspace.

    Must run inside `tenant_session`; row-level security confines the
    insert to the principal's own user and workspace.

    Returns:
        The secret, shown to the person once, and the stored record.
    """
    secret = new_secret()
    row = conn.execute(
        "insert into api_tokens (token_hash, user_id, workspace_id, name, scope) "
        "values (%s, %s, %s, %s, %s) "
        "returning id, name, scope, created_at, revoked_at",
        (digest(secret), principal.user_id, principal.workspace, name, scope),
    ).fetchone()
    assert row is not None
    return secret, ApiToken(*row)


def list_api_tokens(conn: psycopg.Connection) -> list[ApiToken]:
    """The principal's tokens in its workspace, newest first."""
    rows = conn.execute(
        "select id, name, scope, created_at, revoked_at from api_tokens "
        "order by created_at desc"
    ).fetchall()
    return [ApiToken(*r) for r in rows]


def revoke_api_token(conn: psycopg.Connection, token_id: UUID) -> bool:
    """Revoke one of the principal's tokens. False if it is not theirs or gone."""
    row = conn.execute(
        "update api_tokens set revoked_at = now() "
        "where id = %s and revoked_at is null returning id",
        (token_id,),
    ).fetchone()
    return row is not None
