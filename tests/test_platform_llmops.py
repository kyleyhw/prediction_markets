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
    assert llmops.store_key(app_pool, ada, SECRET, MASTER) == "…" + SECRET[-4:]
    assert llmops.own_key(app_pool, ada, MASTER) == SECRET
    assert llmops.own_key(app_pool, bob, MASTER) is None
    (stored,) = pg_owner.execute(
        "select ciphertext from provider_keys where workspace_id = %s", (ada.workspace,)
    ).fetchone()
    assert SECRET.encode() not in bytes(stored)
    assert llmops.delete_key(app_pool, ada) and llmops.key_hint(app_pool, ada) is None


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
