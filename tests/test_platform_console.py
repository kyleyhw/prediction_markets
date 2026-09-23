"""The operator's commands print what they read: every listing runs against
the database, with a workspace paused so the halts table has a UUID in it."""

from __future__ import annotations

import argparse
import contextlib

import pytest

from tests.conftest import needs_db
from vp.platform import console, ops

pytestmark = needs_db


@pytest.mark.parametrize(
    "args",
    [
        {
            "command": "jobs",
            "jobs_command": "list",
            "state": None,
            "kind": None,
            "limit": 5,
        },
        {"command": "jobs", "jobs_command": "stats"},
        {"command": "admin", "admin_command": "halts"},
        {"command": "admin", "admin_command": "costs", "month": None},
        {"command": "admin", "admin_command": "audit"},
    ],
)
def test_each_listing_prints(
    args, pg_owner, two_workspaces, monkeypatch, capsys
) -> None:
    ada = two_workspaces["a"]
    ops.halt(pg_owner, "console test", ada.workspace)
    monkeypatch.setattr(
        console, "owner_connection", lambda: contextlib.nullcontext(pg_owner)
    )
    try:
        console.operator_command(argparse.Namespace(**args))
    finally:
        ops.resume(pg_owner, ada.workspace)
    out = capsys.readouterr().out
    if args.get("admin_command") == "halts":
        assert str(ada.workspace) in out and "console test" in out
