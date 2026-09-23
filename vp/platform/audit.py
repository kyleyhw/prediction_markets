"""The platform's audit chain: who halted, paused, budgeted or archived what.

Entries have the paper ledger's shape and hash (`vp.paper.ledger`), in one
chain for the whole platform, in `audit_entries` (migration 0004), which
only the owner and the `vp_audit_append` function can reach. Each entry
names the principal that acted, so a halt or a budget change is always
attributable to someone.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from vp.markets.schema import utc_now_iso
from vp.paper.ledger import GENESIS, entry_hash, verify_entries
from vp.platform.principal import Principal


def append(
    conn: psycopg.Connection, kind: str, data: dict[str, Any], principal: Principal
) -> dict[str, Any]:
    """Chain one audit entry; retries if another writer got there first."""
    for _ in range(5):
        head = conn.execute("select * from vp_audit_head()").fetchone()
        entry: dict[str, Any] = {
            "seq": (head[0] + 1) if head else 0,
            "at": utc_now_iso(),
            "kind": kind,
            "data": json.loads(
                json.dumps(
                    {
                        **data,
                        "principal": {
                            "subject": principal.subject,
                            "method": str(principal.auth_method),
                            "roles": sorted(principal.roles),
                        },
                    },
                    default=str,
                )
            ),
            "prev": head[1] if head else GENESIS,
        }
        entry["hash"] = entry_hash(entry)
        try:
            with conn.transaction():
                conn.execute(
                    "select vp_audit_append(%s, %s)", (Jsonb(entry), entry["hash"])
                )
            return entry
        except psycopg.errors.SerializationFailure:
            continue
    raise RuntimeError("could not append to the audit chain after five attempts")


def entries(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """The whole chain, in order. Owner connections only."""
    return [r[0] for r in conn.execute("select entry from audit_entries order by seq")]


def verify(conn: psycopg.Connection) -> int | None:
    """The first broken entry's sequence number, or None."""
    return verify_entries(entries(conn))
