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
anyway, to find the previous hash without scanning the chain. A paper
cycle appends inside `batch()`: one transaction for the whole cycle.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.markets.schema import utc_now_iso
from vp.paper.ledger import GENESIS, entry_hash, verify_entries
from vp.platform.archive import archived_entries
from vp.platform.db import tenant_session
from vp.platform.observe import LEDGER_APPEND_SECONDS, timed
from vp.platform.principal import Principal
from vp.platform.storage import ObjectStore


def _as_stored(value: Any) -> Any:
    """The value as `jsonb` will give it back. Postgres numbers have no
    negative zero, so -0.0 is stored as 0.0; hashing -0.0 would break the
    chain the moment the entry was read (found 2026-09-23)."""
    if isinstance(value, float) and value == 0.0:
        return 0.0
    if isinstance(value, dict):
        return {k: _as_stored(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_stored(v) for v in value]
    return value


# Verified entries after the checkpoint before it moves on (Phase 21).
CHECKPOINT_EVERY = 200


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
        # A batch belongs to the thread that opened it; appends from other
        # threads keep queueing on the head row as usual.
        self._local = threading.local()

    @property
    def _batch(self) -> list[dict[str, Any]] | None:
        return getattr(self._local, "batch", None)

    @_batch.setter
    def _batch(self, value: list[dict[str, Any]] | None) -> None:
        self._local.batch = value

    def append(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        """Chain one entry onto the account and return it."""
        if self._batch is not None:
            entry = self._chain(kind, data, self._batch[-1])
            self._batch.append(entry)
            return entry
        with (
            timed(LEDGER_APPEND_SECONDS),
            self.pool.connection() as conn,
            tenant_session(conn, self.principal),
        ):
            entry = self._chain(kind, data, self._head(conn))
            self._write(conn, [entry])
        return entry

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Hold the account's head for a run of appends and write them at once.

        A paper cycle appends hundreds of entries; one transaction, one lock
        of the head row and one pipelined insert replace a transaction each.
        The entries are chained exactly as single appends chain them. They are
        not visible to `entries()` until the block ends, and if it raises
        none is written, so a cycle lands whole or not at all.
        """
        if self._batch is not None:
            raise RuntimeError("the ledger is already in a batch")
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            pending = [self._head(conn)]
            self._batch = pending
            try:
                yield
                self._write(conn, pending[1:])
            finally:
                self._batch = None

    def _head(self, conn: psycopg.Connection) -> dict[str, Any]:
        """Lock the account's head row and return it as a pseudo-entry."""
        conn.execute(
            "insert into ledger_heads (account_id, workspace_id, seq, hash) "
            "values (%s, %s, -1, %s) on conflict (account_id) do nothing",
            (self.account_id, self.principal.workspace, GENESIS),
        )
        head = conn.execute(
            "select seq, hash from ledger_heads where account_id = %s for update",
            (self.account_id,),
        ).fetchone()
        if head is None:
            raise PermissionError("no such paper account in this workspace")
        return {"seq": head[0], "hash": head[1]}

    @staticmethod
    def _chain(kind: str, data: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "seq": prev["seq"] + 1,
            "at": utc_now_iso(),
            "kind": kind,
            # A JSON round trip gives the stored copy the types JSON has,
            # so the hash covers what a reader will get back.
            "data": _as_stored(json.loads(json.dumps(data))),
            "prev": prev["hash"],
        }
        entry["hash"] = entry_hash(entry)
        return entry

    def _write(self, conn: psycopg.Connection, entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        with conn.cursor() as cur:
            cur.executemany(
                "insert into ledger_entries "
                "(account_id, workspace_id, seq, at, kind, entry, hash) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        self.account_id,
                        self.principal.workspace,
                        e["seq"],
                        e["at"],
                        e["kind"],
                        Jsonb(e),
                        e["hash"],
                    )
                    for e in entries
                ],
            )
        conn.execute(
            "update ledger_heads set seq = %s, hash = %s where account_id = %s",
            (entries[-1]["seq"], entries[-1]["hash"], self.account_id),
        )

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

    def _checkpoint(self) -> tuple[int, str, dict[str, Any]] | None:
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            row = conn.execute(
                "select seq, hash, state from ledger_checkpoints where account_id = %s",
                (self.account_id,),
            ).fetchone()
        return (int(row[0]), row[1], row[2]) if row else None

    def _after(self, seq: int) -> list[dict[str, Any]] | None:
        """The entries after ``seq``, or None when they are not all in the
        database (the checkpoint is older than the archived months)."""
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            rows = conn.execute(
                "select entry from ledger_entries where account_id = %s and seq > %s "
                "order by seq",
                (self.account_id, seq),
            ).fetchall()
        out = [r[0] for r in rows]
        return None if out and out[0]["seq"] != seq + 1 else out

    def resume(self, initial_cash: float) -> tuple[dict[str, Any], list] | None:
        """The accounts at the verified checkpoint and the entries after it,
        for `vp.paper.loop.replay`; None without a usable checkpoint."""
        from vp.paper.loop import accounts_from

        cp = self._checkpoint()
        if cp is None:
            return None
        rest = self._after(cp[0])
        return None if rest is None else (accounts_from(cp[2]), rest)

    def verify(self) -> int | None:
        """The sequence number of the first broken entry, or None.

        From the verified checkpoint when there is one; the whole chain
        otherwise, and then a checkpoint is written. The checkpoint moves on
        once ``CHECKPOINT_EVERY`` verified entries follow it. Only this
        method writes checkpoints, so one never covers an unverified entry.
        """
        from vp.paper.loop import accounts_from, apply

        cp = self._checkpoint()
        rest = self._after(cp[0]) if cp else None
        if cp is None or rest is None:
            entries = list(self.entries())
            broken = verify_entries(entries)
            if broken is None and entries:
                self._save(entries[-1], apply({}, entries, self._cash()))
            return broken
        broken = verify_entries(rest, start=(cp[0], cp[1]))
        if broken is None and len(rest) >= CHECKPOINT_EVERY:
            self._save(rest[-1], apply(accounts_from(cp[2]), rest, self._cash()))
        return broken

    def verify_all(self) -> int | None:
        """The whole chain from its first entry, ignoring the checkpoint (the
        daily check that old entries were not changed)."""
        return verify_entries(self.entries())

    def _cash(self) -> float:
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            row = conn.execute(
                "select initial_cash from paper_accounts where id = %s",
                (self.account_id,),
            ).fetchone()
        return float(row[0]) if row else 1000.0

    def _save(self, entry: dict[str, Any], accounts: dict[str, Any]) -> None:
        from vp.paper.loop import state_of

        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            conn.execute(
                "insert into ledger_checkpoints (account_id, seq, hash, state) "
                "values (%s, %s, %s, %s) on conflict (account_id) do update set "
                "seq = excluded.seq, hash = excluded.hash, state = excluded.state, "
                "at = now() where ledger_checkpoints.seq < excluded.seq",
                (
                    self.account_id,
                    entry["seq"],
                    entry["hash"],
                    Jsonb(state_of(accounts)),
                ),
            )

    def export_jsonl(self) -> str:
        """The chain as the file ledger writes it, one entry per line."""
        return "".join(json.dumps(e, sort_keys=True) + "\n" for e in self.entries())
