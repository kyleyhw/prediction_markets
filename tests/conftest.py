"""Shared fixtures. The seed is drawn by NumPy, never hard-coded, and printed so
a failing run can be reproduced."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="session")
def seed() -> int:
    value = int(np.random.default_rng().integers(2**32))
    print(f"\nrandom seed for this session: {value}")
    return value


# ------------------------------------------------------------ the database
# Fixtures for the tests that need Postgres. They skip unless both test URLs
# are set (see tests/test_platform_db.py for how), so `pytest -q` stays
# offline by default.

import os  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from uuid import UUID, uuid4  # noqa: E402

OWNER_URL = os.environ.get("VP_TEST_DATABASE_URL", "")
APP_URL = os.environ.get("VP_TEST_APP_DATABASE_URL", "")
needs_db = pytest.mark.skipif(
    not (OWNER_URL and APP_URL),
    reason="set VP_TEST_DATABASE_URL and VP_TEST_APP_DATABASE_URL",
)


@pytest.fixture(scope="session")
def pg_owner() -> Iterator:
    """An owner connection with every migration applied."""
    from vp.platform.db import connect, migrate

    if not (OWNER_URL and APP_URL):
        pytest.skip("set VP_TEST_DATABASE_URL and VP_TEST_APP_DATABASE_URL")
    conn = connect(OWNER_URL)
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def app_pool(pg_owner) -> Iterator:
    """A pool of `vp_app` connections, the role the policies bind."""
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        APP_URL, min_size=1, max_size=4, kwargs={"autocommit": True}, open=True
    )
    yield pool
    pool.close()


@pytest.fixture
def two_workspaces(pg_owner) -> Iterator[dict]:
    """Two people, each the owner of their own workspace, as principals."""
    from vp.platform.principal import AuthMethod, Principal, Role

    tag = uuid4().hex[:8]
    people: dict[str, Principal] = {}
    ids: list[tuple[UUID, UUID]] = []
    with pg_owner.transaction():
        for side in ("a", "b"):
            (ws,) = pg_owner.execute(
                "insert into workspaces (name) values (%s) returning id",
                (f"ws-{side}-{tag}",),
            ).fetchone()
            (user,) = pg_owner.execute(
                "insert into users (email) values (%s) returning id",
                (f"{side}-{tag}@example.test",),
            ).fetchone()
            pg_owner.execute(
                "insert into memberships (workspace_id, user_id, role) "
                "values (%s, %s, 'owner')",
                (ws, user),
            )
            people[side] = Principal(
                subject=str(user),
                auth_method=AuthMethod.SESSION,
                workspace=ws,
                roles=frozenset({Role.OWNER}),
            )
            ids.append((ws, user))
    yield people
    with pg_owner.transaction():
        pg_owner.execute(
            "delete from jobs where workspace_id = any(%s)", ([w for w, _ in ids],)
        )
        pg_owner.execute(
            "delete from workspaces where id = any(%s)", ([w for w, _ in ids],)
        )
        pg_owner.execute("delete from users where id = any(%s)", ([u for _, u in ids],))
