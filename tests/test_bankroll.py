"""Unit tests for vp.backtest.bankroll on a hand-checkable bet sequence."""

from __future__ import annotations

import numpy as np
import pytest

from vp.backtest import bankroll

# Five bets chosen to exercise a win, a loss, a new high, a drawdown from that
# high and a partial recovery: equity 100 -> 110 -> 105 -> 125 -> 95 -> 110.
PNL = np.array([10.0, -5.0, 20.0, -30.0, 15.0])
CASH = 100.0


def test_equity_curve() -> None:
    assert bankroll.equity_curve(PNL, CASH).tolist() == [
        110.0,
        105.0,
        125.0,
        95.0,
        110.0,
    ]


def test_max_drawdown_from_running_peak() -> None:
    # Peak 125 after bet 3, trough 95 after bet 4: (95 - 125) / 125.
    assert bankroll.max_drawdown(
        bankroll.equity_curve(PNL, CASH), CASH
    ) == pytest.approx(-0.24)


def test_first_bet_loss_counts_against_initial_cash() -> None:
    equity = bankroll.equity_curve(np.array([-10.0, 5.0]), CASH)
    assert bankroll.max_drawdown(equity, CASH) == pytest.approx(-0.10)


def test_per_bet_returns_are_finite_after_ruin() -> None:
    # Bankroll hits zero, so the next return is undefined and reported as 0.0.
    returns = bankroll.per_bet_returns(np.array([-100.0, 10.0]), CASH)
    assert returns.tolist() == [-1.0, 0.0]


def test_bet_stats() -> None:
    stats = bankroll.bet_stats(PNL, CASH)
    assert stats.count == 5
    assert stats.total_return == pytest.approx(0.10)
    assert stats.win_rate == pytest.approx(0.6)
    assert stats.profit_factor == pytest.approx(45.0 / 35.0)
    assert stats.max_consecutive_losses == 1


def test_bet_stats_empty() -> None:
    assert bankroll.bet_stats(np.array([]), CASH).count == 0


def test_permutation_test_bounds_and_invariance(seed: int) -> None:
    result = bankroll.permutation_test(PNL, CASH, n_simulations=200, seed=seed)
    assert 0.0 <= result.p_value_sharpe <= 1.0
    assert 0.0 <= result.p_value_max_drawdown <= 1.0
    assert result.simulated_sharpe_p5 <= result.simulated_sharpe_p95
    # The same seed reproduces the same result.
    again = bankroll.permutation_test(PNL, CASH, n_simulations=200, seed=seed)
    assert again == result


def test_permutation_test_rejects_short_sequences(seed: int) -> None:
    with pytest.raises(ValueError):
        bankroll.permutation_test(PNL[:2], CASH, n_simulations=10, seed=seed)


def test_bootstrap_interval_ordered(seed: int) -> None:
    result = bankroll.bootstrap_sharpe(
        PNL, CASH, n_bootstrap=200, confidence=0.9, seed=seed
    )
    assert result.lower <= result.upper
    assert 0.0 <= result.probability_positive <= 1.0
    with pytest.raises(ValueError):
        bankroll.bootstrap_sharpe(PNL, CASH, n_bootstrap=10, confidence=1.0, seed=seed)


def test_walk_forward_windows_chain_bankroll() -> None:
    result = bankroll.walk_forward(PNL, CASH, n_windows=2)
    assert [w.count for w in result.windows] == [2, 3]
    # Second window starts from the 105 it inherits and ends at 110.
    assert result.windows[1].total_return == pytest.approx(110.0 / 105.0 - 1.0)
    assert result.profitable_windows == 2
    with pytest.raises(ValueError):
        bankroll.walk_forward(PNL, CASH, n_windows=3)
