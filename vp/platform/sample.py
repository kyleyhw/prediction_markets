"""The sample strategies' paper account, one for everyone (plan, flag F17).

Before 2026-09-23 every workspace opened its own account running the same
sample strategies on the same capture, so every one held the same orders
(`tests/reports/phase13_platform.md`). Now the platform runs one account in
a workspace of its own (migration 0014) and every workspace reads it. A
person gets an account of their own when they have a strategy of their own
(Phase 15).

The platform writes to the account as a system user in the sample
workspace, through the same row-level security as anyone's jobs; a
workspace reads it only through two `SECURITY DEFINER` functions, so no
tenancy policy is widened.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from vp.paper.ledger import verify_entries
from vp.platform.archive import archived_entries
from vp.platform.db import tenant_session
from vp.platform.principal import AuthMethod, Principal, Role
from vp.platform.storage import ObjectStore

#: The workspace the sample account lives in, and the user the platform acts
#: as there (migration 0014).
SAMPLE_WORKSPACE = UUID("00000000-0000-0000-0000-00000000a002")
PLATFORM_USER = UUID("00000000-0000-0000-0000-00000000a001")
#: The sample strategies: the market's own price as the yardstick, a coin
#: flip, team ratings and past weather.
SAMPLE_FORECASTERS = ["market", "constant", "elo", "climatology"]


def sample_principal() -> Principal:
    """Who the platform acts as when it trades the sample account."""
    return Principal(
        subject=str(PLATFORM_USER),
        auth_method=AuthMethod.JOB,
        workspace=SAMPLE_WORKSPACE,
        roles=frozenset({Role.EDITOR}),
    )


def sample_account(pool: ConnectionPool) -> dict[str, Any] | None:
    """The sample account as any workspace may read it, or None before the
    platform has opened it."""
    with pool.connection() as conn:
        cur = conn.cursor(row_factory=dict_row)
        return cur.execute("select * from vp_sample_account()").fetchone()


def ensure_sample_account(pool: ConnectionPool) -> UUID:
    """Open the sample account if it is not open yet; returns its id. Its
    domain list is `*`, every domain the engine has, so a new domain joins
    it without a migration."""
    principal = sample_principal()
    with pool.connection() as conn, tenant_session(conn, principal):
        # The cycle and the settlement may both be first; one opens it.
        conn.execute("select pg_advisory_xact_lock(hashtext('vp_sample_account'))")
        row = conn.execute(
            "select id from paper_accounts order by created_at limit 1"
        ).fetchone()
        if row is None:
            row = conn.execute(
                "insert into paper_accounts (workspace_id, name, domains, "
                "forecasters, created_by) values (%s, 'Sample strategies', "
                "'{*}', %s, %s) returning id",
                (SAMPLE_WORKSPACE, SAMPLE_FORECASTERS, PLATFORM_USER),
            ).fetchone()
    assert row is not None
    return row[0]


class SampleLedger:
    """The sample account's ledger, read-only, for any workspace."""

    def __init__(
        self, pool: ConnectionPool, account_id: UUID, store: ObjectStore | None
    ) -> None:
        self.pool = pool
        self.account_id = account_id
        self.store = store

    def append(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        raise PermissionError("the sample account is the platform's to write")

    def entries(self) -> Iterator[dict[str, Any]]:
        if self.store is not None:
            yield from archived_entries(self.store, self.account_id)
        with self.pool.connection() as conn:
            rows = conn.execute("select * from vp_sample_entries()").fetchall()
        for (entry,) in rows:
            yield entry

    def last(self) -> dict[str, Any] | None:
        entries = list(self.entries())
        return entries[-1] if entries else None

    def verify(self) -> int | None:
        return verify_entries(self.entries())
