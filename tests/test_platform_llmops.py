"""Paid model calls on the platform: own keys under envelope encryption,
the cross-worker limit on concurrent calls, and a backtest that uses the
model charging what it spent to the right payer."""

from __future__ import annotations

import base64
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag

from tests.conftest import needs_db
from vp.platform import llmops

MASTER = base64.b64encode(os.urandom(32)).decode()
SECRET = "sk-ant-test-" + "x" * 40  # pragma: allowlist secret


def test_a_sealed_key_opens_only_with_its_master_key() -> None:
    ciphertext, wrapped = llmops.seal(SECRET, MASTER)
    assert SECRET.encode() not in ciphertext + wrapped
    assert llmops.unseal(ciphertext, wrapped, MASTER) == SECRET
    other = base64.b64encode(os.urandom(32)).decode()
    with pytest.raises(InvalidTag):
        llmops.unseal(ciphertext, wrapped, other)
    with pytest.raises(llmops.KeysUnavailable):
        llmops.seal(SECRET, None)


@needs_db
def test_an_own_key_is_the_workspace_s_alone(
    app_pool, pg_owner, two_workspaces
) -> None:
    ada, bob = two_workspaces["a"], two_workspaces["b"]
    hint = llmops.store_connection(
        app_pool,
        ada,
        provider="anthropic",
        model=None,
        key=SECRET,
        base_url=None,
        master_key=MASTER,
    )
    assert hint == "…" + SECRET[-4:]
    assert llmops.own_connection(app_pool, ada, MASTER) == {
        "provider": "anthropic",
        "model": None,
        "base_url": None,
        "key": SECRET,
    }
    assert llmops.own_connection(app_pool, bob, MASTER) is None
    (stored,) = pg_owner.execute(
        "select ciphertext from provider_keys where workspace_id = %s", (ada.workspace,)
    ).fetchone()
    assert SECRET.encode() not in bytes(stored)
    assert llmops.delete_connection(app_pool, ada)
    assert llmops.connection(app_pool, ada) is None


@needs_db
def test_the_limit_holds_across_callers(app_pool) -> None:
    slots = llmops.Slots(app_pool, "test-limit", 2)
    active, peak, lock = 0, 0, threading.Lock()

    def call() -> None:
        nonlocal active, peak
        with slots.hold():
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.1)
            with lock:
                active -= 1

    threads = [threading.Thread(target=call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 2


@needs_db
def test_a_model_backtest_charges_its_tokens_to_the_payer(
    app_pool, pg_owner, two_workspaces, monkeypatch, tmp_path: Path
) -> None:
    from tests.test_llm import FakeMessages
    from vp.markets.store import write_markets
    from vp.platform import budgets
    from vp.platform.config import Settings
    from vp.platform.handlers import Services, handlers
    from vp.platform.jobs import Worker, enqueue
    from vp.platform.storage import LocalStore, SharedRoot, publish_dataset

    ada = two_workspaces["a"]
    from tests.test_forecast import EPL

    path = tmp_path / "resolved.parquet"
    write_markets(path, EPL)
    store = LocalStore(tmp_path / "store")
    publish_dataset(store, "epl", path, "20260901T000000Z")
    # Every EPL market needs a price at the cutoff to be forecast; give the
    # model one market and a history for it.
    from vp.markets.store import write_history

    hist = tmp_path / "h.parquet"
    write_history(
        hist,
        market_id="5",
        clob_token_id="50",
        outcome="Yes",
        points=[{"timestamp": "2026-03-04T00:00:00Z", "implied_probability": 0.4}],
        bar_minutes=1440,
    )
    store.put_file("shared/histories/epl/5.parquet", hist)
    fake = FakeMessages([0.6] * 20)
    monkeypatch.setattr(
        llmops,
        "client_for",
        lambda *a, **k: (SimpleNamespace(messages=fake), "own_key"),
    )
    services = Services(
        settings=Settings(database_url="unused", data_root=tmp_path),
        pool=app_pool,
        store=store,
        shared=SharedRoot(store, tmp_path / "cache"),
        work_dir=tmp_path,
    )
    job = enqueue(
        app_pool,
        ada,
        "backtest",
        {"domain": "epl", "forecasters": ["market", "llm"], "kinds": ["match"]},
    )
    Worker(app_pool, handlers(), ("backtest",), services=services).run_once()
    state, result, error = pg_owner.execute(
        "select state, result, error from jobs where id = %s", (job,)
    ).fetchone()
    assert state == "succeeded", error
    rows = budgets.breakdown(app_pool, ada)
    assert rows and rows[0]["forecaster"] == "llm" and rows[0]["paid_by"] == "own_key"
    assert rows[0]["input_tokens"] > 0 and rows[0]["model"] == "claude-opus-5"
    # Spending on one's own key does not use the platform budget.
    assert budgets.standing(app_pool, ada).charged_usd == 0


def _say_country(pool, principal, code: str | None) -> None:
    from psycopg.types.json import Jsonb

    from vp.platform.db import tenant_session

    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "insert into user_settings (user_id, settings) "
            "values (vp_current_user_id(), %s) on conflict (user_id) do "
            "update set settings = excluded.settings",
            (Jsonb({"country": code}),),
        )


@needs_db
def test_any_provider_connects_and_the_demo_answers_the_rest(
    app_pool, two_workspaces
) -> None:
    """docs/models.md: a workspace's own model from any provider answers its
    calls; without one the free demo does, for people where it may."""
    from vp.forecast.llm import resolve_model
    from vp.platform.config import Settings

    ada, bob = two_workspaces["a"], two_workspaces["b"]
    demo = Settings(
        database_url="unused",
        master_key=MASTER,
        demo_api_key="g" * 39,  # pragma: allowlist secret
    )
    for bad in (
        {"provider": "groq", "model": None, "key": SECRET},  # no model named
        {"provider": "groq", "model": "llama", "key": "short"},
        {
            "provider": "custom",
            "model": "m",
            "key": None,
            "base_url": "https://10.1.1.1/v1",
        },
        {"provider": "ollama", "model": "qwen", "key": None},  # your own copy only
        {"provider": "command", "model": "m", "key": None},
    ):
        with pytest.raises(ValueError):
            kw: dict[str, Any] = {"base_url": None, "master_key": MASTER, **bad}
            llmops.store_connection(
                app_pool,
                ada,
                **kw,
            )
    llmops.store_connection(
        app_pool,
        ada,
        provider="groq",
        model="llama-3.3-70b",
        key=SECRET,
        base_url="https://ignored.example",  # a preset keeps its own address
        master_key=MASTER,
    )
    assert llmops.connection(app_pool, ada) == {
        "provider": "groq",
        "model": "llama-3.3-70b",
        "base_url": None,
        "hint": "…" + SECRET[-4:],
    }
    client, paid = llmops.client_for(app_pool, ada, demo)
    assert (
        paid == "own_key" and resolve_model(client, "claude-opus-5") == "llama-3.3-70b"
    )
    # A second connection replaces the first: one own model per workspace.
    llmops.store_connection(
        app_pool,
        ada,
        provider="custom",
        model="my-model",
        key=None,
        base_url="https://8.8.8.8/v1",
        master_key=MASTER,
    )
    assert (llmops.connection(app_pool, ada) or {}).get("provider") == "custom"
    # Bob has none: the demo, once he says where he is, and only there.
    _say_country(app_pool, bob, None)
    with pytest.raises(llmops.DemoUnavailable) as caught:
        llmops.client_for(app_pool, bob, demo)
    assert caught.value.code == "country_needed"
    _say_country(app_pool, bob, "DE")
    with pytest.raises(llmops.DemoUnavailable) as caught:
        llmops.client_for(app_pool, bob, demo)
    assert caught.value.code == "region_blocked" and "own copy" in str(caught.value)
    _say_country(app_pool, bob, "US")
    client, paid = llmops.client_for(app_pool, bob, demo)
    assert paid == "platform" and client.free
    assert resolve_model(client, "claude-opus-5") == "gemini-3.1-flash-lite"
    assert client.messages.batches is None, "the demo model has no batch API"
    # A copy whose demo is its own model has no country rule.
    local = Settings(
        database_url="unused",
        demo_provider="custom",
        demo_model="qwen",
        demo_base_url="http://127.0.0.1:9/v1",
        allow_private_model_urls=True,
    )
    _say_country(app_pool, bob, "DE")
    assert llmops.client_for(app_pool, bob, local)[1] == "platform"
    with pytest.raises(llmops.DemoUnavailable):
        llmops.client_for(app_pool, bob, Settings(database_url="unused"))
    llmops.delete_connection(app_pool, ada)


@needs_db
def test_the_demo_allowance_is_counted_per_workspace_and_platform(
    app_pool, pg_owner, two_workspaces
) -> None:
    from vp.platform.config import Settings

    ada, bob = two_workspaces["a"], two_workspaces["b"]
    pg_owner.execute("delete from demo_calls")
    tight = Settings(
        database_url="unused",
        demo_api_key="g" * 39,  # pragma: allowlist secret
        demo_workspace_daily_calls=2,
        demo_daily_calls=3,
    )
    for who in (ada, bob):
        _say_country(app_pool, who, "IN")
    assert llmops.demo_check(app_pool, ada, tight) == 2
    llmops.take_demo_call(app_pool, ada, tight)
    llmops.take_demo_call(app_pool, ada, tight)
    with pytest.raises(llmops.DemoUnavailable) as caught:
        llmops.take_demo_call(app_pool, ada, tight)  # Ada's two are gone
    assert caught.value.code == "used_up"
    llmops.take_demo_call(app_pool, bob, tight)
    with pytest.raises(llmops.DemoUnavailable):
        llmops.demo_check(app_pool, bob, tight)  # the platform's three are gone
    # The count is written only through the function, never directly.
    with pytest.raises(Exception, match="permission denied"):
        with app_pool.connection() as conn:
            from vp.platform.db import tenant_session

            with tenant_session(conn, bob):
                conn.execute("delete from demo_calls")
    # Each call through a demo client takes one before it is made.
    pg_owner.execute("delete from demo_calls")
    client, _ = llmops.client_for(app_pool, ada, tight)
    client._client.messages.create = lambda **k: "answered"  # no network
    client.messages._messages = client._client.messages
    assert client.messages.create(model="m", messages=[], max_tokens=1) == "answered"
    assert llmops.demo_check(app_pool, ada, tight) == 1
    pg_owner.execute("delete from demo_calls")


@needs_db
def test_the_platform_daily_cap_holds_across_workspaces(
    app_pool, two_workspaces
) -> None:
    from decimal import Decimal

    from vp.platform import budgets

    ada, bob = two_workspaces["a"], two_workspaces["b"]
    cap = float(budgets.platform_spent_today(app_pool)) + 1.0
    budgets.reserve(app_pool, ada, 0.6, cap)
    with pytest.raises(budgets.PlatformCapReached):
        budgets.reserve(app_pool, bob, 0.5, cap)
    # Within its own month Bob has room; the platform's day does not.
    assert budgets.standing(app_pool, bob).remaining_usd >= Decimal("0.5")
    budgets.reserve(app_pool, bob, 0.4, cap)
    assert budgets.platform_spent_today(app_pool) == pytest.approx(cap, abs=1e-6)
    # Releasing returns the room.
    budgets.settle_job(app_pool, ada, uuid4(), 0.6, [])
    budgets.settle_job(app_pool, bob, uuid4(), 0.4, [])
    budgets.reserve(app_pool, bob, 0.9, cap)
    budgets.settle_job(app_pool, bob, uuid4(), 0.9, [])


def test_a_refused_connection_is_said_in_one_plain_sentence() -> None:
    """A simulated user was shown a provider's raw 401 (2026-10-13)."""
    said = llmops._plain_failure(
        "Anthropic (Claude)",
        None,
        "Error code: 401 - {'type': 'error', 'error': {'type': "
        "'authentication_error', 'message': 'invalid x-api-key'}}",
    )
    assert said == (
        "Anthropic (Claude) did not accept that key. Check that you copied all of it."
    )
    assert "no model named 'gpt-x'" in llmops._plain_failure("OpenAI", "gpt-x", "404")
