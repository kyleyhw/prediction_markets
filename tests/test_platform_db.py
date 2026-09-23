"""Migrations, and the tenancy boundary they create.

These are the only tests in the suite that need a server, so they skip
unless both connection strings are set, keeping `pytest -q` offline by
default. To run them:

    VP_TEST_DATABASE_URL='postgresql:///vp_dev?host=/var/run/postgresql&user=postgres' \\
    VP_TEST_APP_DATABASE_URL='postgresql:///vp_dev?host=/var/run/postgresql&user=vp_app' \\
    uv run pytest tests/test_platform_db.py

The first must own the tables (it runs the migrations); the second must be
`vp_app`, which owns nothing. Pointing both at the same role would make
every assertion below pass for the wrong reason, so the fixture checks
they differ and that the second is not a superuser.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest

from vp.platform.db import (
    MigrationError,
    TransactionStateError,
    applied_migrations,
    connect,
    migrate,
    tenant_session,
)
from vp.platform.principal import AuthMethod, Principal, Role

OWNER_URL = os.environ.get("VP_TEST_DATABASE_URL", "")
APP_URL = os.environ.get("VP_TEST_APP_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not (OWNER_URL and APP_URL),
    reason="set VP_TEST_DATABASE_URL and VP_TEST_APP_DATABASE_URL",
)


@pytest.fixture(scope="module")
def owner() -> Iterator[psycopg.Connection]:
    """An owner connection with the schema applied."""
    conn = connect(OWNER_URL)
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def tenants(owner: psycopg.Connection) -> Iterator[dict[str, UUID]]:
    """Two workspaces with one member each, committed so another role sees them."""
    tag = uuid4().hex[:8]
    ids: dict[str, UUID] = {}
    with owner.transaction():
        for side in ("a", "b"):
            ws = owner.execute(
                "insert into workspaces (name) values (%s) returning id",
                (f"workspace-{side}-{tag}",),
            ).fetchone()
            user = owner.execute(
                "insert into users (email) values (%s) returning id",
                (f"{side}-{tag}@example.test",),
            ).fetchone()
            assert ws and user
            ids[f"ws_{side}"], ids[f"user_{side}"] = ws[0], user[0]
            owner.execute(
                "insert into memberships (workspace_id, user_id, role) "
                "values (%s, %s, 'owner')",
                (ids[f"ws_{side}"], ids[f"user_{side}"]),
            )
    yield ids
    with owner.transaction():
        owner.execute(
            "delete from workspaces where id = any(%s)",
            ([ids["ws_a"], ids["ws_b"]],),
        )
        owner.execute(
            "delete from users where id = any(%s)",
            ([ids["user_a"], ids["user_b"]],),
        )


@pytest.fixture
def app(tenants: dict[str, UUID]) -> Iterator[psycopg.Connection]:
    """A connection as `vp_app`, which the policies actually apply to."""
    conn = connect(APP_URL)
    row = conn.execute(
        "select current_user, usesuper from pg_user where usename = current_user"
    ).fetchone()
    assert row, "the application role must exist"
    assert row[0] != "postgres", "the app must not connect as the owner"
    assert not row[1], "the app must not connect as a superuser: RLS is bypassed"
    yield conn
    conn.close()


def _principal(tenants: dict[str, UUID], side: str) -> Principal:
    return Principal(
        subject=str(tenants[f"user_{side}"]),
        auth_method=AuthMethod.SESSION,
        workspace=tenants[f"ws_{side}"],
        roles=frozenset({Role.OWNER}),
    )


def test_migrations_are_recorded_and_applying_twice_is_a_no_op(
    owner: psycopg.Connection,
) -> None:
    assert migrate(owner) == []
    names = [m.name for m in applied_migrations(owner)]
    assert "0001_foundation.sql" in names
    assert names == sorted(names)


def test_an_edited_migration_is_refused(owner: psycopg.Connection, tmp_path) -> None:
    """The database and the repository must not disagree about the schema."""
    dir_ = tmp_path / "migrations"
    dir_.mkdir()
    sql = dir_ / "9999_probe.sql"
    sql.write_text("select 1;\n")
    assert migrate(owner, directory=dir_) == ["9999_probe.sql"]
    sql.write_text("select 2;\n")
    with pytest.raises(MigrationError, match="immutable once applied"):
        migrate(owner, directory=dir_)
    with owner.transaction():
        owner.execute("delete from schema_migrations where name = '9999_probe.sql'")


def test_without_a_context_the_application_sees_nothing(
    app: psycopg.Connection,
) -> None:
    """The fail-closed default: an unset workspace matches no row."""
    for table in ("workspaces", "users", "memberships"):
        count = app.execute(f"select count(*) from {table}").fetchone()
        assert count and count[0] == 0, table


def test_a_workspace_sees_itself_and_not_the_other(
    app: psycopg.Connection, tenants: dict[str, UUID]
) -> None:
    with tenant_session(app, _principal(tenants, "a")) as conn:
        rows = conn.execute("select id from workspaces").fetchall()
    assert [r[0] for r in rows] == [tenants["ws_a"]]


def test_a_query_that_forgets_its_filter_returns_nothing_not_someone_else(
    app: psycopg.Connection, tenants: dict[str, UUID]
) -> None:
    """The point of row-level security, stated as a test."""
    with tenant_session(app, _principal(tenants, "a")) as conn:
        rows = conn.execute("select workspace_id from memberships").fetchall()
    assert {r[0] for r in rows} == {tenants["ws_a"]}
    assert tenants["ws_b"] not in {r[0] for r in rows}


def test_naming_another_workspace_explicitly_still_returns_nothing(
    app: psycopg.Connection, tenants: dict[str, UUID]
) -> None:
    with tenant_session(app, _principal(tenants, "a")) as conn:
        rows = conn.execute(
            "select id from workspaces where id = %s", (tenants["ws_b"],)
        ).fetchall()
    assert rows == []


def test_a_user_sees_only_their_own_record(
    app: psycopg.Connection, tenants: dict[str, UUID]
) -> None:
    with tenant_session(app, _principal(tenants, "a")) as conn:
        rows = conn.execute("select id from users").fetchall()
    assert [r[0] for r in rows] == [tenants["user_a"]]


def test_writing_into_another_workspace_is_refused(
    app: psycopg.Connection, tenants: dict[str, UUID]
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_session(app, _principal(tenants, "a")) as conn:
            conn.execute(
                "insert into memberships (workspace_id, user_id, role) "
                "values (%s, %s, 'viewer')",
                (tenants["ws_b"], tenants["user_a"]),
            )


def test_deleting_another_workspaces_rows_touches_nothing(
    app: psycopg.Connection, tenants: dict[str, UUID]
) -> None:
    with tenant_session(app, _principal(tenants, "a")) as conn:
        conn.execute(
            "delete from memberships where workspace_id = %s", (tenants["ws_b"],)
        )
    with tenant_session(app, _principal(tenants, "b")) as conn:
        rows = conn.execute("select count(*) from memberships").fetchone()
    assert rows and rows[0] == 1


def test_the_context_does_not_outlive_its_transaction(
    app: psycopg.Connection, tenants: dict[str, UUID]
) -> None:
    """A pooled connection must not carry one tenant's scope into the next."""
    with tenant_session(app, _principal(tenants, "a")) as conn:
        assert conn.execute("select vp_current_workspace()").fetchone()
    leaked = app.execute("select vp_current_workspace()").fetchone()
    assert leaked and leaked[0] is None


def test_a_principal_without_a_workspace_cannot_open_a_session(
    app: psycopg.Connection,
) -> None:
    with pytest.raises(PermissionError, match="workspace"):
        with tenant_session(app, Principal.anonymous()):
            pass


def test_an_unattributable_principal_cannot_open_a_session(
    app: psycopg.Connection, tenants: dict[str, UUID]
) -> None:
    anon_in_workspace = Principal(
        subject="anonymous",
        auth_method=AuthMethod.ANONYMOUS,
        workspace=tenants["ws_a"],
        roles=frozenset({Role.VIEWER}),
    )
    with pytest.raises(PermissionError):
        with tenant_session(app, anon_in_workspace):
            pass


def test_a_connection_already_in_a_transaction_is_refused(
    tenants: dict[str, UUID],
) -> None:
    """The savepoint hazard the autocommit rule exists to prevent.

    A non-autocommit connection opens a transaction on its first statement.
    `conn.transaction()` would then be a savepoint, the workspace would
    outlive the block, and the next request on a pooled connection would
    inherit it. Refuse instead.
    """
    conn = connect(APP_URL, autocommit=False)
    try:
        conn.execute("select 1")
        with pytest.raises(TransactionStateError, match="savepoint"):
            with tenant_session(conn, _principal(tenants, "a")):
                pass
    finally:
        conn.close()
