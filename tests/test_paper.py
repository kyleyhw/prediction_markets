"""The forward loop, settlement and leakage check against fakes.

The source is the fake of test_dataset (one open CS2 match with a book);
the forecaster is a constant whose belief sits well above the ask, so an
order is placed at the touch and capped at the resting size. A second cycle
places nothing (the position is open). Settlement uses a fake market fetch
that first reports pending, then a resolved winner.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.test_dataset import fake_book, fake_history, fake_iter_events, fake_search
from vp.domains import CS2
from vp.forecast.baselines import Constant, MarketPrice
from vp.markets.polymarket import PolymarketSource
from vp.paper import leakage
from vp.paper.ledger import Ledger
from vp.paper.loop import replay, run_cycle, settle

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def resolved_record(state: str, winner: str | None) -> dict[str, Any]:
    return {
        "market_id": None,
        "condition_id": "0x6",
        "question": "Spirit vs Team Falcons",
        "status": "resolved" if state == "resolved" else "closed",
        "trading_closed": True,
        "resolution": {"state": state, "winning_outcome": winner},
        "outcomes": [
            {"outcome": "Yes", "clob_token_id": "60", "implied_probability": 1.0},
            {"outcome": "No", "clob_token_id": "61", "implied_probability": 0.0},
        ],
    }


def make_source(records: list[dict[str, Any]]) -> PolymarketSource:
    def fetch_market(identifier: str, *, depth: int = 0) -> dict[str, Any]:
        return records.pop(0)

    return PolymarketSource(
        iter_events=fake_iter_events,
        search_events=fake_search,
        fetch_history=fake_history,
        fetch_book=fake_book,
        fetch_market=fetch_market,
        now=lambda: "2026-09-13T00:00:00Z",
    )


def test_cycle_orders_at_the_touch_and_settles(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "paper" / "ledger.jsonl")
    source = make_source(
        [resolved_record("pending", None), resolved_record("resolved", "Yes")]
    )
    forecasters = [MarketPrice(), Constant(0.9, name="sure")]
    counts = run_cycle(
        CS2, forecasters, source, tmp_path, ledger, depth=1, initial_cash=100.0, now=NOW
    )
    # The market baseline forecasts the snapshot price (0.5) and never orders;
    # the constant forecasts and orders.
    assert counts == {
        "snapshot": 1,
        "parsed": 1,
        "forecasts": 2,
        "recorded": 2,
        "orders": 1,
    }
    accounts = replay(ledger, 100.0)
    order = accounts["sure"].open["6"]
    # Kelly on 0.9 at ask 0.51 exceeds the 5% cap: stake 5 = 9.8 shares, but the
    # touch rests 7 shares, so the fill is capped at 7 shares for 3.57.
    assert order["side"] == "yes" and order["price"] == 0.51
    assert order["shares"] == 7.0 and order["stake"] == pytest.approx(3.57)
    # The fake market states no fee, so the zero fallback applies and says so.
    assert order["fee"] == 0.0 and order["fee_source"] == "assumed"
    assert [e["kind"] for e in ledger.entries()] == [
        "cycle",
        "forecast",
        "forecast",
        "order",
    ]

    # Second cycle: the market baseline forecasts again (it never holds a
    # position), but the price has not moved, so nothing new is recorded;
    # the constant's position is open, so no new order.
    counts = run_cycle(
        CS2, forecasters, source, tmp_path, ledger, depth=1, initial_cash=100.0, now=NOW
    )
    assert counts["orders"] == 0 and counts["forecasts"] == 1
    assert counts["recorded"] == 0 and len(list(ledger.entries())) == 5

    # Settlement: pending first, then resolved Yes.
    assert settle(source, ledger, initial_cash=100.0) == {
        "open": 1,
        "settled": 0,
        "pending": 1,
        "void": 0,
        "errors": 0,
    }
    assert settle(source, ledger, initial_cash=100.0)["settled"] == 1
    account = replay(ledger, 100.0)["sure"]
    assert account.open == {} and account.bankroll == pytest.approx(100 + 7.0 - 3.57)
    last = ledger.last()
    assert last is not None and last["kind"] == "settlement"
    assert last["data"]["brier"] == pytest.approx((0.9 - 1) ** 2)
    assert ledger.verify() is None


def test_order_pays_the_markets_own_fee(tmp_path: Path) -> None:
    """A market stating a 0.05 rate is charged at it, not at the fallback."""

    def search_with_fees(query: str, **kwargs: Any) -> dict[str, Any]:
        result = fake_search(query, **kwargs)
        return {
            **result,
            "events": [
                {
                    **event,
                    "markets": [
                        {**m, "fee_rate": 0.05, "fee_exponent": 1.0}
                        for m in event["markets"]
                    ],
                }
                for event in result["events"]
            ],
        }

    source = PolymarketSource(
        iter_events=fake_iter_events,
        search_events=search_with_fees,
        fetch_history=fake_history,
        fetch_book=fake_book,
        now=lambda: "2026-09-13T00:00:00Z",
    )
    ledger = Ledger(tmp_path / "paper" / "ledger.jsonl")
    run_cycle(
        CS2,
        [Constant(0.9, name="sure")],
        source,
        tmp_path,
        ledger,
        depth=1,
        initial_cash=100.0,
        now=NOW,
    )
    order = replay(ledger, 100.0)["sure"].open["6"]
    per_share = 0.05 * 0.51 * 0.49
    assert order["fee_source"] == "market" and order["fee_rate"] == 0.05
    assert order["price"] == pytest.approx(0.51 + per_share)
    assert order["fee"] == pytest.approx(order["shares"] * per_share)


def test_leakage_gap(tmp_path: Path) -> None:
    back = {"sure": np.array([0.01, 0.02, 0.03, 0.02]), "other": np.array([0.1])}
    forward = {"sure": np.array([0.2, 0.3, 0.25, 0.25]), "missing": np.array([0.5])}
    rows = leakage.gaps(back, forward, seed=1, n_bootstrap=500)
    assert [g.forecaster for g in rows] == ["sure"]
    g = rows[0]
    assert g.gap == pytest.approx(0.25 - 0.02)
    assert g.gap_low > 0, "a gap this large excludes zero"
    assert "| sure | 4 | 0.0200 | 4 | 0.2500 |" in leakage.summary(rows)


def test_a_forecast_is_recorded_again_only_when_it_moves(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "paper" / "ledger.jsonl")
    source = make_source([resolved_record("pending", None)])
    recorded = []
    # Close to the market, so it never finds an edge and never holds a position.
    for p in (0.5, 0.503, 0.51):
        counts = run_cycle(
            CS2, [Constant(p, name="drift")], source, tmp_path, ledger, depth=1, now=NOW
        )
        assert counts["forecasts"] == 1 and counts["orders"] == 0
        recorded.append(counts["recorded"])
    assert recorded == [1, 0, 1]
    said = [e["data"]["p_hat"] for e in ledger.entries() if e["kind"] == "forecast"]
    assert said == [0.5, 0.51]


def test_an_account_stakes_only_the_cash_it_has(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "paper" / "ledger.jsonl")
    # 98 of the 100 is already staked on another market.
    ledger.append(
        "order",
        {"forecaster": "sure", "market_id": "elsewhere", "stake": 98.0, "shares": 1},
    )
    source = make_source([resolved_record("pending", None)])
    counts = run_cycle(
        CS2,
        [Constant(0.9, name="sure")],
        source,
        tmp_path,
        ledger,
        depth=1,
        initial_cash=100.0,
        now=NOW,
    )
    assert counts["orders"] == 1
    order = replay(ledger, 100.0)["sure"].open["6"]
    assert order["stake"] == pytest.approx(2.0)  # not the 5 the cap allows
    # With nothing left, the next market gets nothing.
    ledger.append(
        "order",
        {"forecaster": "sure", "market_id": "more", "stake": 50.0, "shares": 1},
    )
    ledger.append("settlement", {"forecaster": "sure", "market_id": "6", "pnl": 0.0})
    counts = run_cycle(
        CS2,
        [Constant(0.9, name="sure")],
        source,
        tmp_path,
        ledger,
        depth=1,
        initial_cash=100.0,
        now=NOW,
    )
    assert counts["orders"] == 0
