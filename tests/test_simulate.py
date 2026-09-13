"""The fill simulator on a hand-checkable sequence of opportunities."""

from __future__ import annotations

import pytest

from vp.backtest.simulate import Opportunity, simulate


def test_simulate_fills_settles_and_compounds() -> None:
    opps = [
        # Edge on yes at ask 0.51: f = 0.25 * (0.6-0.51)/0.49; wins.
        Opportunity("a", "2026-01-02", p_hat=0.6, q=0.50, label=1),
        # Listed out of order; settles first. Edge on no at 1-bid = 0.51; loses.
        Opportunity("b", "2026-01-01", p_hat=0.4, q=0.50, label=1),
        # Inside the spread: skipped.
        Opportunity("c", "2026-01-03", p_hat=0.505, q=0.50, label=1),
    ]
    bets = simulate(opps, initial_cash=100.0, half_spread=0.01, max_fraction=1.0)
    assert [b.market_id for b in bets] == ["b", "a"]
    first = bets[0]
    f = 0.25 * (0.6 - 0.51) / 0.49
    assert first.side == "no" and first.stake == pytest.approx(100 * f)
    assert first.pnl == pytest.approx(-first.stake)
    assert first.bankroll_after == pytest.approx(100 - first.stake)
    second = bets[1]
    assert second.side == "yes" and second.stake == pytest.approx(
        first.bankroll_after * f
    )
    assert second.shares == pytest.approx(second.stake / 0.51)
    assert second.pnl == pytest.approx(second.shares - second.stake)
    assert second.bankroll_after == pytest.approx(first.bankroll_after + second.pnl)


def test_simulate_stops_at_ruin_and_caps() -> None:
    opps = [Opportunity(str(i), f"2026-01-{i:02d}", 0.99, 0.5, 0) for i in range(1, 6)]
    bets = simulate(opps, initial_cash=10.0, max_fraction=0.05)
    # Every bet stakes 5% of the running bankroll and loses; the bankroll
    # decays geometrically and never reaches zero, so all five fill.
    assert len(bets) == 5 and bets[-1].bankroll_after == pytest.approx(10 * 0.95**5)
    assert all(
        b.stake == pytest.approx(0.05 * (10 * 0.95**i)) for i, b in enumerate(bets)
    )
