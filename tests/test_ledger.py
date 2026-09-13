"""Chain integrity of the ledger, including detection of every kind of tamper."""

from __future__ import annotations

import json
from pathlib import Path

from vp.paper.ledger import GENESIS, Ledger


def test_ledger_chains_and_verifies(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "l" / "ledger.jsonl")
    assert ledger.verify() is None and ledger.last() is None
    a = ledger.append("order", {"market": "1", "stake": 5.0})
    b = ledger.append("settlement", {"market": "1", "pnl": -5.0})
    assert (a["seq"], a["prev"]) == (0, GENESIS) and b["prev"] == a["hash"]
    assert ledger.verify() is None
    assert [e["kind"] for e in ledger.entries()] == ["order", "settlement"]


def test_ledger_detects_edit_deletion_and_reorder(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    for i in range(3):
        ledger.append("order", {"i": i})
    lines = path.read_text().splitlines()
    # Edit the payload of entry 1.
    edited = json.loads(lines[1])
    edited["data"]["i"] = 99
    path.write_text("\n".join([lines[0], json.dumps(edited), lines[2]]) + "\n")
    assert ledger.verify() == 1
    # Delete entry 1: entry 2's prev no longer matches.
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert ledger.verify() == 1
    # Swap entries 1 and 2.
    path.write_text("\n".join([lines[0], lines[2], lines[1]]) + "\n")
    assert ledger.verify() == 1
    path.write_text("\n".join(lines) + "\n")
    assert ledger.verify() is None
