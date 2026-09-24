"""The paper ledger in Postgres: the same chain as the file, per account,
isolated per workspace, and verifiable offline from an export."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.conftest import needs_db
from vp.paper.ledger import Ledger
from vp.platform.db import tenant_session
from vp.platform.ledger import PgLedger

pytestmark = needs_db


def open_account(pool, principal, name="Sample strategies"):
    with pool.connection() as conn, tenant_session(conn, principal):
        (account,) = conn.execute(
            "insert into paper_accounts (workspace_id, name, domains, forecasters, created_by) "
            "values (%s, %s, %s, %s, %s) returning id",
            (principal.workspace, name, ["cs2"], ["constant"], principal.user_id),
        ).fetchone()
    return account


def test_the_chain_is_the_file_ledgers_chain(
    app_pool, two_workspaces, tmp_path: Path
) -> None:
    ada = two_workspaces["a"]
    ledger = PgLedger(app_pool, ada, open_account(app_pool, ada))
    ledger.append("cycle", {"domain": "cs2", "markets": 3})
    # Awkward floats must hash the same after the database round trip.
    ledger.append(
        "order", {"price": 0.1 + 0.2, "fee": 1e-7, "shares": 12.345678901234567}
    )
    ledger.append("settlement", {"pnl": -3.57, "label": 0, "q": None, "fee": -0.0})
    assert ledger.verify() is None
    assert [e["seq"] for e in ledger.entries()] == [0, 1, 2]
    last = ledger.last()
    assert last is not None and last["kind"] == "settlement"
    # The export is a file the engine's own Ledger accepts.
    path = tmp_path / "export.jsonl"
    path.write_text(ledger.export_jsonl())
    assert Ledger(path).verify() is None
    # And a change to any entry in it is caught.
    lines = path.read_text().splitlines()
    path.write_text(
        "\n".join([lines[0], lines[1].replace("0.30000000000000004", "0.3"), lines[2]])
    )
    assert Ledger(path).verify() == 1


def test_another_workspace_sees_no_entries_and_cannot_append(
    app_pool, two_workspaces
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    account = open_account(app_pool, ada)
    PgLedger(app_pool, ada, account).append("cycle", {"domain": "epl"})
    assert list(PgLedger(app_pool, bob, account).entries()) == []
    with pytest.raises(Exception):  # noqa: B017 - row-level security refuses it
        PgLedger(app_pool, bob, account).append("cycle", {"domain": "epl"})
    assert PgLedger(app_pool, ada, account).verify() is None


def test_concurrent_appends_queue_rather_than_fork(app_pool, two_workspaces) -> None:
    ada = two_workspaces["a"]
    ledger = PgLedger(app_pool, ada, open_account(app_pool, ada))
    errors: list[BaseException] = []

    def write(n: int) -> None:
        try:
            for i in range(10):
                ledger.append("forecast", {"writer": n, "i": i})
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    entries = list(ledger.entries())
    assert len(entries) == 40 and ledger.verify() is None


def test_partitions_are_reached_only_through_the_policy(
    app_pool, two_workspaces
) -> None:
    """A partition named directly would skip the parent's row-level security,
    so `vp_app` holds no privilege on any per-workspace partition."""
    ada = two_workspaces["a"]
    PgLedger(app_pool, ada, open_account(app_pool, ada)).append("cycle", {})
    with app_pool.connection() as conn:
        names = [
            r[0]
            for r in conn.execute(
                "select c.relname from pg_inherits i join pg_class c on c.oid = i.inhrelid "
                "join pg_class p on p.oid = i.inhparent "
                "where p.relname in ('ledger_entries', 'forecasts')"
            ).fetchall()
        ]
        assert names
        for name in names:
            (allowed,) = conn.execute(
                "select has_table_privilege(current_user, %s, 'select')", (name,)
            ).fetchone()
            assert not allowed, name


def test_an_archived_month_leaves_postgres_and_the_chain_still_verifies(
    pg_owner, app_pool, two_workspaces, tmp_path: Path
) -> None:
    from datetime import date

    from vp.platform.archive import archive_key, archive_month
    from vp.platform.storage import LocalStore

    ada = two_workspaces["a"]
    account = open_account(app_pool, ada, name="Archived")
    store = LocalStore(tmp_path / "store")
    ledger = PgLedger(app_pool, ada, account, store=store)
    # Two entries dated in an old month, as if written then: the owner moves
    # them into a partition of their own before the chain continues today.
    month = date(2024, 1, 1)
    first = ledger.append("cycle", {"n": 1})
    second = ledger.append("cycle", {"n": 2})
    with pg_owner.transaction():
        pg_owner.execute(
            "create table if not exists ledger_entries_202401 partition of ledger_entries "
            "for values from ('2024-01-01') to ('2024-02-01')"
        )
        for e in (first, second):
            # Rewriting `at` in both the row and the hashed entry keeps the
            # chain valid: this stands in for entries written in January 2024.
            e["at"] = "2024-01-15T00:00:00Z"
        from vp.paper.ledger import entry_hash

        first["hash"] = entry_hash(first)
        second["prev"] = first["hash"]
        second["hash"] = entry_hash(second)
        pg_owner.execute("delete from ledger_entries where account_id = %s", (account,))
        from psycopg.types.json import Jsonb

        for e in (first, second):
            pg_owner.execute(
                "insert into ledger_entries (account_id, workspace_id, seq, at, kind, entry, hash) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                (
                    account,
                    ada.workspace,
                    e["seq"],
                    e["at"],
                    e["kind"],
                    Jsonb(e),
                    e["hash"],
                ),
            )
        pg_owner.execute(
            "update ledger_heads set seq = 1, hash = %s where account_id = %s",
            (second["hash"], account),
        )
    ledger.append("cycle", {"n": 3})
    moved = archive_month(pg_owner, store, "ledger_entries", month)
    assert moved >= 2 and store.get_bytes(archive_key("ledger_entries", month))
    (gone,) = pg_owner.execute("select to_regclass('ledger_entries_202401')").fetchone()
    assert gone is None
    # Postgres now holds only the newest entry; with the archive, all three
    # verify from the first.
    assert [e["seq"] for e in PgLedger(app_pool, ada, account).entries()] == [2]
    assert [e["seq"] for e in ledger.entries()] == [0, 1, 2]
    assert ledger.verify() is None
    # Deleting the workspace rewrites the month without its rows.
    from vp.platform.archive import archived_entries, purge_workspace

    assert purge_workspace(store, ada.workspace) >= 2
    assert list(archived_entries(store, account)) == []


def test_a_batch_chains_as_single_appends_do_and_lands_whole(
    app_pool, two_workspaces
) -> None:
    ada = two_workspaces["a"]
    ledger = PgLedger(app_pool, ada, open_account(app_pool, ada))
    ledger.append("cycle", {"domain": "cs2"})
    with ledger.batch():
        for i in range(50):
            ledger.append("forecast", {"i": i})
        assert len(list(ledger.entries())) == 1  # not visible until it ends
    ledger.append("cycle", {"domain": "epl"})
    entries = list(ledger.entries())
    assert [e["seq"] for e in entries] == list(range(52)) and ledger.verify() is None
    # A batch that raises writes nothing, and the chain carries on from its head.
    with pytest.raises(RuntimeError, match="halfway"), ledger.batch():
        ledger.append("forecast", {"i": "lost"})
        raise RuntimeError("halfway")
    ledger.append("cycle", {"domain": "weather"})
    assert len(list(ledger.entries())) == 53 and ledger.verify() is None


def test_a_checkpoint_verifies_and_replays_only_what_follows(
    app_pool, two_workspaces, pg_owner
) -> None:
    """Phase 21: a year's chain cost a cycle 1.1 s read whole; a verified
    checkpoint gives the same accounts from the entries after it."""
    from vp.paper.loop import apply, replay
    from vp.platform import ledger as pl

    ada = two_workspaces["a"]
    account = open_account(app_pool, ada, "Checkpointed")
    ledger = PgLedger(app_pool, ada, account)
    with ledger.batch():
        for i in range(pl.CHECKPOINT_EVERY + 50):
            ledger.append(
                "order" if i % 2 == 0 else "settlement",
                {"forecaster": "elo", "market_id": f"m{i // 2}", "pnl": 1.0},
            )
    assert ledger.resume(1000.0) is None  # no checkpoint before a verification
    assert ledger.verify() is None
    (seq,) = pg_owner.execute(
        "select seq from ledger_checkpoints where account_id = %s", (account,)
    ).fetchone()
    assert seq == pl.CHECKPOINT_EVERY + 49
    ledger.append("order", {"forecaster": "elo", "market_id": "late"})
    got = ledger.resume(1000.0)
    assert got is not None and [e["seq"] for e in got[1]] == [seq + 1]
    full = apply({}, ledger.entries(), 1000.0)
    fast = replay(ledger, 1000.0)
    assert {k: (a.bankroll, set(a.open)) for k, a in fast.items()} == {
        k: (a.bankroll, set(a.open)) for k, a in full.items()
    }
    # A change after the checkpoint is caught by every cycle; a change before
    # it only by the daily check of the whole chain.
    with pg_owner.transaction():
        pg_owner.execute(
            "update ledger_entries set entry = jsonb_set(entry, '{data,pnl}', '9') "
            "where account_id = %s and seq in (3, %s)",
            (account, seq + 1),
        )
    assert ledger.verify() == seq + 1
    assert ledger.verify_all() == 3
