"""The live safety layer: every refusal path of the guard, the kill switch,
environment separation, approvals and credential access. Nothing here can
sign or send an order; the tests pin that the gate fails closed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vp.live import controls
from vp.live.mandate import Guard, Mandate, OrderRequest, replay_state
from vp.paper.ledger import Ledger

# Ledger entries are stamped with the real clock, so the test clock is the
# real one too, a minute ahead of any entry written during the test.
NOW = datetime.now(tz=timezone.utc) + timedelta(minutes=1)
MANDATE = {
    "version": 1,
    "max_order_notional": 10,
    "max_market_exposure": 15,
    "max_total_exposure": 25,
    "max_orders_per_day": 3,
    "max_daily_loss": 8,
    "allowed_domains": ["cs2", "epl"],
    "expires_at": (datetime.now(tz=timezone.utc) + timedelta(days=30)).isoformat(),
}


@pytest.fixture
def mandate(tmp_path: Path) -> Path:
    path = tmp_path / "mandate.json"
    path.write_text(json.dumps(MANDATE))
    return path


def order(stake: float = 5.0, market: str = "m1", domain: str = "cs2") -> OrderRequest:
    return OrderRequest(domain, market, "yes", 0.5, stake)


def test_guard_allows_within_mandate_and_refuses_each_cap(
    mandate: Path, tmp_path: Path
) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    guard = Guard(mandate, ledger)
    assert guard.check(order(), now=NOW).allowed
    assert "max_order_notional" in guard.check(order(stake=11), now=NOW).reason
    assert "not in mandate" in guard.check(order(domain="weather"), now=NOW).reason
    assert "expired" in guard.check(order(), now=NOW + timedelta(days=31)).reason
    assert not guard.check(OrderRequest("cs2", "m1", "yes", 1.0, 5.0), now=NOW).allowed
    assert not guard.check(order(stake=0.0), now=NOW).allowed
    # Two open orders of 8 on m1: a third of 8 would exceed the market cap of 15,
    # but 5 on m2 is fine; then total exposure 21 + 5 crosses 25.
    for _ in range(2):
        ledger.append("order", {"market_id": "m1", "stake": 8.0})
    assert "max_market_exposure" in guard.check(order(stake=8), now=NOW).reason
    assert guard.check(order(market="m2"), now=NOW).allowed
    ledger.append("order", {"market_id": "m2", "stake": 5.0})
    assert (
        "max_total_exposure" in guard.check(order(stake=5, market="m3"), now=NOW).reason
    )
    # Three orders today hit the daily count.
    assert (
        "max_orders_per_day" in guard.check(order(stake=1, market="m3"), now=NOW).reason
    )
    # Settling m1 at a loss of 9 frees its exposure but halts trading (cap 8).
    ledger.append("settlement", {"market_id": "m1", "pnl": -9.0})
    state = replay_state(ledger, NOW)
    assert state.open_by_market == {"m2": 5.0} and state.orders_last_day == 3
    assert "max_daily_loss" in guard.check(order(stake=1, market="m3"), now=NOW).reason
    # Two days later both windows have cleared.
    assert guard.check(order(stake=1, market="m3"), now=NOW + timedelta(days=2)).allowed


def test_guard_fails_closed_on_defects(mandate: Path, tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    guard = Guard(tmp_path / "missing.json", ledger)
    assert "mandate unreadable" in guard.check(order(), now=NOW).reason
    for bad in (
        {},
        {**MANDATE, "version": 2},
        {**MANDATE, "max_daily_loss": 0},
        {**MANDATE, "expires_at": "soon"},
    ):
        mandate.write_text(json.dumps(bad))
        assert not Guard(mandate, ledger).check(order(), now=NOW).allowed
    with pytest.raises(ValueError):
        Mandate.load(mandate)
    mandate.write_text(json.dumps(MANDATE))
    ledger.append("order", {"market_id": "m1", "stake": 1.0})
    lines = ledger.path.read_text().splitlines()
    ledger.path.write_text(lines[0].replace('"stake": 1.0', '"stake": 2.0') + "\n")
    assert (
        Guard(mandate, ledger).check(order(), now=NOW).reason == "ledger chain broken"
    )


def test_kill_switch_and_environment(tmp_path: Path) -> None:
    stop = tmp_path / "STOP"
    assert not controls.stopped(stop)
    stop.touch()
    assert controls.stopped(stop)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    controls.ensure_environment(ledger, controls.Environment.PAPER)
    controls.ensure_environment(ledger, controls.Environment.PAPER)
    with pytest.raises(RuntimeError, match="refusing"):
        controls.ensure_environment(ledger, controls.Environment.LIVE)
    unlabelled = Ledger(tmp_path / "old.jsonl")
    unlabelled.append("order", {})
    with pytest.raises(RuntimeError, match="unlabelled"):
        controls.ensure_environment(unlabelled, controls.Environment.LIVE)


def test_approval_protocol(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    proposal = controls.propose(ledger, {"market_id": "m1", "stake": 1.0})
    assert not controls.approved(ledger, proposal)
    with pytest.raises(ValueError):
        controls.approve(ledger, proposal, "")
    controls.approve(ledger, proposal, "kyle")
    assert controls.approved(ledger, proposal)
    # An approval expires, and it is consumed once an order references it.
    assert not controls.approved(
        ledger, proposal, now=datetime.now(tz=timezone.utc) + timedelta(hours=1)
    )
    assert not controls.approved(ledger, "unknown")
    ledger.append("order", {"market_id": "m1", "stake": 1.0, "proposal": proposal})
    assert not controls.approved(ledger, proposal)


def test_credentials_by_environment() -> None:
    store = {("vibe-predict", "live"): "s3cret"}
    assert (
        controls.load_credential(
            controls.Environment.LIVE, backend=lambda s, u: store.get((s, u))
        )
        == "s3cret"
    )
    with pytest.raises(RuntimeError, match="no credential"):
        controls.load_credential(
            controls.Environment.PAPER, backend=lambda s, u: store.get((s, u))
        )
    with pytest.raises(RuntimeError):
        controls.load_credential(controls.Environment.LIVE)  # no keyring library here
