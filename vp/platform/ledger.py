"""The paper ledger in Postgres: one hash chain per paper account.

`PgLedger` has the interface of `vp.paper.ledger.Ledger` (`append`,
`entries`, `last`, `verify`), so the engine's paper loop writes to it
unchanged, and it stores exactly the entries the file ledger would write,
hashed by the same function. Exporting an account's entries as JSON lines
therefore gives a file `Ledger.verify` accepts, which is how a person can
check their own record without trusting the platform.

Each append is one tenant transaction. It locks the account's head row
(`ledger_heads`) before reading the previous hash, so two writers to one
account queue rather than both chaining onto the same entry; the lock is
the row lock rather than an advisory lock because the head row is needed
anyway, to find the previous hash without scanning the chain.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.markets.schema import utc_now_iso
from vp.paper.ledger import GENESIS, entry_hash, verify_entries
from vp.platform.archive import archived_entries
from vp.platform.db import tenant_session
from vp.platform.observe import LEDGER_APPEND_SECONDS, timed
from vp.platform.principal import Principal
from vp.platform.storage import ObjectStore


class PgLedger:
    """An account's ledger, read and written as `principal`."""

    def __init__(
        self,
        pool: ConnectionPool,
        principal: Principal,
        account_id: UUID,
        store: ObjectStore | None = None,
    ) -> None:
        self.pool = pool
        self.principal = principal
        self.account_id = account_id
        # Where archived months are read from, so a chain older than the
        # retention window still verifies from its first entry.
        self.store = store

    def append(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        """Chain one entry onto the account and return it."""
        workspace = self.principal.workspace
        with (
            timed(LEDGER_APPEND_SECONDS),
            self.pool.connection() as conn,
            tenant_session(conn, self.principal),
        ):
            conn.execute(
                "insert into ledger_heads (account_id, workspace_id, seq, hash) "
                "values (%s, %s, -1, %s) on conflict (account_id) do nothing",
                (self.account_id, workspace, GENESIS),
            )
            head = conn.execute(
                "select seq, hash from ledger_heads where account_id = %s for update",
                (self.account_id,),
            ).fetchone()
            if head is None:
                raise PermissionError("no such paper account in this workspace")
            entry: dict[str, Any] = {
                "seq": head[0] + 1,
                "at": utc_now_iso(),
                "kind": kind,
                # A JSON round trip gives the stored copy the types JSON has,
                # so the hash covers what a reader will get back.
                "data": json.loads(json.dumps(data)),
                "prev": head[1],
            }
            entry["hash"] = entry_hash(entry)
            conn.execute(
                "insert into ledger_entries "
                "(account_id, workspace_id, seq, at, kind, entry, hash) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                (
                    self.account_id,
                    workspace,
                    entry["seq"],
                    entry["at"],
                    kind,
                    Jsonb(entry),
                    entry["hash"],
                ),
            )
            conn.execute(
                "update ledger_heads set seq = %s, hash = %s where account_id = %s",
                (entry["seq"], entry["hash"], self.account_id),
            )
        return entry

    def entries(self) -> Iterator[dict[str, Any]]:
        """The account's entries in chain order, archived months first."""
        if self.store is not None:
            yield from archived_entries(self.store, self.account_id)
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            rows = conn.execute(
                "select entry from ledger_entries where account_id = %s order by seq",
                (self.account_id,),
            ).fetchall()
        for (entry,) in rows:
            yield entry

    def last(self) -> dict[str, Any] | None:
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            row = conn.execute(
                "select entry from ledger_entries where account_id = %s "
                "order by seq desc limit 1",
                (self.account_id,),
            ).fetchone()
        return row[0] if row else None

    def verify(self) -> int | None:
        """The sequence number of the first broken entry, or None."""
        return verify_entries(self.entries())

    def export_jsonl(self) -> str:
        """The chain as the file ledger writes it, one entry per line."""
        return "".join(json.dumps(e, sort_keys=True) + "\n" for e in self.entries())
