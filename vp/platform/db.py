"""Postgres access: migrations, and the connection a tenant query runs on.

Two ways to reach the database, and the difference is the whole tenancy
guarantee:

* **The owner connection** runs migrations and the sign-up path. It owns
  the tables, so row-level security does not apply to it. Nothing else may
  use it.
* **The tenant connection** (`tenant_session`) connects as `vp_app`, which
  owns nothing, and sets the workspace and user on the transaction before
  any statement runs. Every policy in migration 0001 answers against those
  settings, so a query that forgets its filter returns nothing.

The settings are set with `set_config(..., true)`, which is local to the
transaction, so a pooled connection cannot carry one workspace's context
into the next request.

That last guarantee depends on a detail worth stating plainly, because
getting it wrong is silent. A psycopg connection that is *not* in
autocommit mode opens a transaction on its first statement and holds it
open; a `conn.transaction()` block on such a connection is a **savepoint
inside that transaction**, not a transaction of its own. A workspace set
with `set_config(..., true)` would then live until the outer transaction
ended, which is to say until something else committed it or the connection
closed, and the next request on that connection would inherit it. Writes
would be no better off: they would sit uncommitted in the outer
transaction and vanish on close.

So connections here are opened in autocommit mode and every unit of work
is an explicit `conn.transaction()` block, which is then a real
transaction. `tenant_session` and `migrate` both refuse a connection that
is already inside one rather than quietly degrading to a savepoint.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg

from vp.platform.principal import Principal

#: The migrations applied by `migrate`, in filename order.
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_LEDGER = """
create table if not exists schema_migrations (
    name       text primary key,
    checksum   text not null,
    applied_at timestamptz not null default now()
)
"""


class MigrationError(RuntimeError):
    """A migration is missing, out of order, or changed after it was applied."""


class TransactionStateError(RuntimeError):
    """A connection was already in a transaction where one must not be."""


@dataclass(frozen=True)
class AppliedMigration:
    """One row of the migration ledger."""

    name: str
    checksum: str
    applied_at: datetime


def connect(url: str, *, autocommit: bool = True) -> psycopg.Connection:
    """Open one connection in autocommit mode.

    Autocommit is the default, and callers should keep it: see the module
    docstring for why an implicitly-opened transaction turns every later
    `conn.transaction()` into a savepoint. Work that must be atomic goes in
    an explicit `with conn.transaction():` block, which under autocommit is
    a real transaction.

    Args:
        url: a libpq connection string.
        autocommit: leave True unless you have read the module docstring
            and want the caller to drive the transaction.

    Returns:
        The connection. The caller closes it.
    """
    return psycopg.connect(url, autocommit=autocommit)


def _require_idle(conn: psycopg.Connection, what: str) -> None:
    """Refuse a connection that is already inside a transaction."""
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise TransactionStateError(
            f"{what} needs an idle connection: this one is already in a "
            "transaction, so the block below would be a savepoint rather "
            "than a transaction. Open the connection with autocommit=True "
            "(the default) and commit or roll back before calling."
        )


def applied_migrations(conn: psycopg.Connection) -> list[AppliedMigration]:
    """Return the migration ledger in application order."""
    conn.execute(_LEDGER)
    rows = conn.execute(
        "select name, checksum, applied_at from schema_migrations order by name"
    ).fetchall()
    return [AppliedMigration(str(n), str(c), a) for n, c, a in rows]


def migrate(
    conn: psycopg.Connection, *, directory: Path | None = None
) -> list[str]:
    """Apply every migration the database has not seen, in filename order.

    Each runs in its own transaction with its name and checksum, so a
    failure leaves the database at the last complete migration.

    Args:
        conn: an owner connection. Migrations create tables and grants.
        directory: where the `.sql` files live; defaults to this package's.

    Returns:
        The names applied by this call, in order. Empty when up to date.

    Raises:
        MigrationError: a file that was already applied has changed since,
            which means the database and the repository disagree about what
            the schema is.
        TransactionStateError: the connection is already in a transaction,
            so each migration would be a savepoint and none would commit.
    """
    _require_idle(conn, "migrate")
    source = MIGRATIONS_DIR if directory is None else directory
    seen = {m.name: m.checksum for m in applied_migrations(conn)}
    done: list[str] = []
    for path in sorted(source.glob("*.sql")):
        body = path.read_bytes()
        checksum = hashlib.sha256(body).hexdigest()
        if path.name in seen:
            if seen[path.name] != checksum:
                raise MigrationError(
                    f"{path.name} was applied as {seen[path.name][:12]} but is "
                    f"now {checksum[:12]}; migrations are immutable once applied"
                )
            continue
        with conn.transaction():
            # Sent as bytes: psycopg accepts a bytes query, and a decoded
            # str is not a LiteralString, which its overloads require.
            conn.execute(body)
            conn.execute(
                "insert into schema_migrations (name, checksum) values (%s, %s)",
                (path.name, checksum),
            )
        done.append(path.name)
    return done


@contextmanager
def tenant_session(
    conn: psycopg.Connection, principal: Principal
) -> Iterator[psycopg.Connection]:
    """Run a transaction scoped to one principal's workspace.

    Args:
        conn: a connection as `vp_app`, never as the owner or a superuser.
        principal: the actor. Must name a user and a workspace.

    Yields:
        The same connection, inside a transaction whose workspace and user
        settings every row-level security policy answers against.

    Raises:
        PermissionError: the principal names no workspace, or no user, so
            there is no scope to run in.
        TransactionStateError: the connection is already in a transaction,
            so the workspace would outlive this block.
    """
    if principal.workspace is None:
        raise PermissionError("a tenant session needs a workspace")
    user_id = principal.user_id
    _require_idle(conn, "a tenant session")
    with conn.transaction():
        conn.execute(
            "select set_config('vp.workspace_id', %s, true)",
            (str(principal.workspace),),
        )
        conn.execute(
            "select set_config('vp.user_id', %s, true)", (str(user_id),)
        )
        yield conn
