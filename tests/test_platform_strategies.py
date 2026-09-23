"""Strategies on the platform: a conversation compiled by a job, a version
confirmed and frozen, backtested with its manifest and card, traded in
paper by its spec, and memory that is the person's own."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from tests.conftest import needs_db
from tests.test_forecast import root  # noqa: F401 - fixture
from tests.test_platform_handlers import job_row, run_all, services  # noqa: F401
from tests.test_strategy import make_market
from tests.test_strategy_compiler import GOOD, FakeModel, answer, with_
from vp.markets.store import write_markets
from vp.platform import strategies
from vp.platform.db import tenant_session
from vp.platform.handlers import Services
from vp.platform.jobs import enqueue
from vp.platform.ledger import PgLedger

pytestmark = needs_db


def compile_once(app_pool, services, who, monkeypatch, reply, **payload):
    fake = FakeModel(reply)
    monkeypatch.setattr(
        "vp.platform.llmops.client_for", lambda *a, **k: (fake, "platform")
    )
    convo = payload.pop("conversation_id", None) or strategies.open_conversation(
        app_pool, who, payload.pop("strategy_id", None)
    )
    job = enqueue(
        app_pool,
        who,
        "compile",
        {
            "conversation_id": str(convo),
            "words": payload.get("words", "Arsenal by Elo"),
        },
    )
    run_all(app_pool, services, ("compile",))
    return convo, job, fake


def test_a_conversation_becomes_a_frozen_version_that_is_only_its_workspace_s(
    app_pool, pg_owner, two_workspaces, services: Services, monkeypatch
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    strategies.remember(app_pool, ada, "prefers small stakes")
    convo, job, fake = compile_once(
        app_pool, services, ada, monkeypatch, answer("spec", GOOD, "Here it is.")
    )
    row = job_row(pg_owner, job)
    assert row["state"] == "succeeded", row["error"]
    assert row["result"]["kind"] == "spec" and row["result"]["cost_usd"] > 0
    assert "prefers small stakes" in fake.requests[0]["system"][0]["text"]
    turns = strategies.conversation(app_pool, ada, convo)["turns"]
    assert [t["role"] for t in turns] == ["user", "assistant"]
    proposed = turns[1]
    assert proposed["content"]["rendering"][0].startswith("Markets: Premier League")
    made = strategies.confirm(app_pool, ada, convo, proposed["id"])
    assert made["version"] == 1
    listed = strategies.listing(app_pool, ada)
    assert [s["name"] for s in listed] == ["Arsenal by Elo"]
    assert strategies.listing(app_pool, bob) == []
    with pytest.raises(strategies.NotFound):
        strategies.conversation(app_pool, bob, convo)
    # A version is never edited, by anyone.
    with pytest.raises(psycopg.errors.RaiseException):
        pg_owner.execute(
            "update strategy_versions set spec_hash = repeat('0', 64) where id = %s",
            (UUID(made["version_id"]),),
        )
    # Refining in a conversation about the strategy adds version 2 with a diff.
    smaller = with_(GOOD, "sizing", max_fraction=0.02)
    convo2, job2, fake2 = compile_once(
        app_pool,
        services,
        ada,
        monkeypatch,
        answer("spec", smaller),
        strategy_id=UUID(made["strategy_id"]),
        words="smaller stakes",
    )
    assert '"Arsenal FC"' in fake2.requests[0]["system"][0]["text"]  # current spec
    turn = strategies.conversation(app_pool, ada, convo2)["turns"][1]
    assert turn["content"]["changes"] == [["sizing.max_fraction", 0.05, 0.02]]
    second = strategies.confirm(app_pool, ada, convo2, turn["id"])
    assert second["version"] == 2 and second["strategy_id"] == made["strategy_id"]
    found = strategies.detail(app_pool, ada, UUID(made["strategy_id"]))
    assert found["versions"][1]["changes"] == [["sizing.max_fraction", 0.05, 0.02]]
    with pytest.raises(ValueError, match="already in use"):
        strategies.confirm(app_pool, ada, convo2, turn["id"])


def test_a_strategy_is_backtested_with_its_manifest_and_card(
    app_pool, pg_owner, two_workspaces, services: Services, monkeypatch
) -> None:
    ada = two_workspaces["a"]
    constant = with_(with_(GOOD, "belief", forecaster="constant"), "selector", where=[])
    convo, _, _ = compile_once(
        app_pool, services, ada, monkeypatch, answer("spec", constant)
    )
    turn = strategies.conversation(app_pool, ada, convo)["turns"][1]
    made = strategies.confirm(app_pool, ada, convo, turn["id"])
    job = enqueue(
        app_pool, ada, "backtest", {"strategy_version_id": made["version_id"]}
    )
    run_all(app_pool, services, ("backtest",))
    row = job_row(pg_owner, job)
    assert row["state"] == "succeeded", row["error"]
    assert row["result"]["spec_hash"] == made["spec_hash"]
    found = strategies.detail(app_pool, ada, UUID(made["strategy_id"]))
    assert found["status"] == "backtested"
    (run,) = found["runs"]
    assert run["version"] == 1 and run["domain"] == "epl"
    card = run["results"]["card"]
    assert card["spec_hash"] == made["spec_hash"]
    assert card["manifest_hash"] == run["manifest_hash"]
    assert any("markets were scored" in c for c in card["caveats"])  # small n
    with app_pool.connection() as conn, tenant_session(conn, ada):
        (artifacts, manifest) = conn.execute(
            "select artifacts, manifest from runs where id = %s",
            (UUID(run["run_id"]),),
        ).fetchone()
    assert manifest["dataset_version"] == "20260901T000000Z"
    assert services.store.get_bytes(f"{artifacts}/strategy.md")
    assert services.store.get_bytes(f"{artifacts}/manifest.json")


def test_a_strategy_trades_paper_by_its_spec_in_an_account_of_its_own(
    app_pool, pg_owner, two_workspaces, services: Services, monkeypatch, tmp_path: Path
) -> None:
    ada = two_workspaces["a"]
    # A capture newer than the fixture's: one CS2 series ending in 11 hours.
    at = datetime.now(tz=UTC) + timedelta(minutes=1)
    capture = tmp_path / f"{at:%Y%m%dT%H%M%SZ}.parquet"
    write_markets(
        capture,
        [
            make_market(
                market_id="s1",
                condition_id="0xs1",
                question="Counter-Strike: Spirit vs Team Falcons (BO3)",
                domain="cs2",
                parsed={"kind": "match", "team_a": "Spirit", "team_b": "Team Falcons"},
                end_date=(at + timedelta(hours=11)).isoformat(),
                best_bid=0.60,
                best_ask=0.62,
                fee_rate=0.05,
            )
        ],
    )
    services.store.put_file(f"shared/snapshots/cs2/{capture.name}", capture)
    follow = with_(
        with_(
            with_(GOOD, "selector", domains=["cs2"], where=[]),
            "belief",
            forecaster="market",
        ),
        "rule",
        kind="follow",
        follow="favourite",
    )
    follow["name"] = "CS2 favourites"
    convo, _, _ = compile_once(
        app_pool, services, ada, monkeypatch, answer("spec", follow)
    )
    turn = strategies.conversation(app_pool, ada, convo)["turns"][1]
    made = strategies.confirm(app_pool, ada, convo, turn["id"])
    strategy_id = UUID(made["strategy_id"])
    opened = strategies.start_paper(app_pool, ada, strategy_id)
    assert strategies.start_paper(app_pool, ada, strategy_id) == opened  # once
    with app_pool.connection() as conn, tenant_session(conn, ada):
        schedules = conn.execute(
            "select kind, cron from schedules where payload->>'account_id' = %s "
            "order by kind",
            (opened["account_id"],),
        ).fetchall()
    assert schedules == [("paper_cycle", "5 * * * *"), ("settle", "35 * * * *")]
    job = enqueue(app_pool, ada, "paper_cycle", {"account_id": opened["account_id"]})
    run_all(app_pool, services, ("paper_cycle",))
    row = job_row(pg_owner, job)
    assert row["state"] == "succeeded", row["error"]
    ledger = PgLedger(app_pool, ada, UUID(opened["account_id"]))
    orders = [e["data"] for e in ledger.entries() if e["kind"] == "order"]
    assert len(orders) == 1, row["result"]
    order = orders[0]
    assert (order["forecaster"], order["side"], order["event_id"]) == (
        "follow",
        "yes",
        "e",
    )
    assert order["stake"] == pytest.approx(10.0)  # 1% of 1,000, flat
    assert order["fee"] > 0  # the market's own fee
    assert strategies.detail(app_pool, ada, strategy_id)["status"] == "paper"
    strategies.retire(app_pool, ada, strategy_id)
    with app_pool.connection() as conn, tenant_session(conn, ada):
        enabled = conn.execute(
            "select bool_or(enabled) from schedules where payload->>'account_id' = %s",
            (opened["account_id"],),
        ).fetchone()
    assert enabled == (False,)
    with pytest.raises(ValueError, match="retired"):
        strategies.start_paper(app_pool, ada, strategy_id)


def test_memory_is_the_person_s_own_and_goes_with_them(
    app_pool, two_workspaces
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    note = strategies.remember(app_pool, ada, "  likes   weather markets ")
    assert [m["note"] for m in strategies.memory(app_pool, ada)] == [
        "likes weather markets"
    ]
    assert strategies.memory(app_pool, bob) == []
    assert not strategies.forget(app_pool, bob, UUID(note))
    assert strategies.forget(app_pool, ada, UUID(note))
    assert strategies.memory(app_pool, ada) == []
