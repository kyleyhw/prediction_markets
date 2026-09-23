"""Hash-chained, append-only JSONL ledger.

Every entry carries the SHA-256 of the previous entry and of its own
content, so the file is a chain: editing or deleting any entry breaks every
hash after it, and :meth:`Ledger.verify` finds the first break. This is the
record paper trading and, later, live execution write to; nothing in it is
ever rewritten, and a corrected fact is a new entry that says so.

Entry shape::

    {"seq": n, "at": ISO-8601 UTC, "kind": str, "data": {...},
     "prev": hex, "hash": hex}

``hash`` is over the canonical JSON of the entry without the ``hash`` key,
so the chain covers the sequence number, time, kind and payload.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol

from vp.markets.schema import utc_now_iso

GENESIS = "0" * 64


class ChainLedger(Protocol):
    """What the paper loop needs of a ledger: this file's, or the
    platform's in Postgres, which stores the same chain."""

    def append(self, kind: str, data: dict[str, Any]) -> dict[str, Any]: ...

    def entries(self) -> Iterator[dict[str, Any]]: ...

    def last(self) -> dict[str, Any] | None: ...

    def verify(self) -> int | None: ...


def entry_hash(entry: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of an entry without its ``hash`` key.

    Public so that every store of this chain (the file here, the platform's
    Postgres ledger) hashes the same bytes and one ``verify`` fits all.
    """
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Ledger:
    """Append and verify entries in a JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def entries(self) -> Iterator[dict[str, Any]]:
        """Yield entries in file order."""
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    def last(self) -> dict[str, Any] | None:
        last = None
        for last in self.entries():
            pass
        return last

    def append(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        """Write one entry chained to the previous one and return it."""
        previous = self.last()
        entry: dict[str, Any] = {
            "seq": (previous["seq"] + 1) if previous else 0,
            "at": utc_now_iso(),
            "kind": kind,
            "data": data,
            "prev": previous["hash"] if previous else GENESIS,
        }
        entry["hash"] = entry_hash(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def verify(self) -> int | None:
        """Return the sequence number of the first broken entry, or ``None``."""
        return verify_entries(self.entries())


def verify_entries(entries: Iterable[dict[str, Any]]) -> int | None:
    """The sequence number of the first broken entry in a chain, or ``None``."""
    prev = GENESIS
    for expected, entry in enumerate(entries):
        if (
            entry.get("seq") != expected
            or entry.get("prev") != prev
            or entry_hash(entry) != entry.get("hash")
        ):
            return expected
        prev = entry["hash"]
    return None
