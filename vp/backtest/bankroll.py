"""Bankroll statistics for a sequence of settled bets.

The unit of analysis is a per-bet profit-and-loss array ``pnl`` in currency
units, in settlement order, with a starting bankroll ``initial_cash``. From it
the equity curve is $E_0 = C$, $E_k = C + \\sum_{i \\le k} \\text{pnl}_i$.

Adapted from HKUDS/Vibe-Trading ``agent/backtest/metrics.py`` and
``agent/backtest/validation.py`` (MIT); see ``NOTICE`` and
``docs/provenance.md``. Upstream works on bar-indexed equity of continuous
instruments with per-venue annualisation tables, trade-record classes and
turnover series, none of which apply to a binary contract that settles once at
0 or 1. What is kept is the arithmetic and its edge-case guards: the drawdown
high-water mark seeded at ``initial_cash``, the ``ddof=1`` small-sample guard,
the Monte Carlo trade-order permutation test, the bootstrap confidence interval
and walk-forward consistency. The Sharpe-like ratio here is *per bet* and is
not annualised, because bets have no fixed time base.

Randomised procedures take an explicit ``seed`` so results are reproducible
and no seed is hard-coded in the library; the caller supplies it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

# Minimum number of bets for a permutation test or bootstrap to say anything:
# with fewer than three there are at most six orderings and the p-value grid
# is coarser than any conclusion drawn from it. Upstream uses the same floor.
_MIN_BETS = 3

# Denominator guard. Added to a standard deviation before division so that a
# constant PnL sequence yields a large finite ratio rather than a division by
# zero; small against any realistic return scale, and the upstream value.
_STD_EPS = 1e-10


def equity_curve(pnl: NDArray[np.float64], initial_cash: float) -> NDArray[np.float64]:
    """Bankroll after each bet, $E_k = C + \\sum_{i \\le k} \\text{pnl}_i$."""
    return initial_cash + np.cumsum(pnl, dtype=np.float64)


def per_bet_returns(
    pnl: NDArray[np.float64], initial_cash: float
) -> NDArray[np.float64]:
    """Return of each bet relative to the bankroll before it.

    $r_k = \\text{pnl}_k / E_{k-1}$, with $E_0$ the initial bankroll.

    Defined only where the prior bankroll is positive; otherwise reported as
    ``0.0`` rather than ``inf`` or ``nan``.
    """
    equity = equity_curve(pnl, initial_cash)
    prev = np.concatenate(([initial_cash], equity[:-1]))
    usable = np.isfinite(prev) & (prev > 0)
    return np.where(usable, pnl / np.where(usable, prev, 1.0), 0.0)


def max_drawdown(equity: NDArray[np.float64], initial_cash: float) -> float:
    """Worst peak-to-trough fall as a fraction of the peak, $\\min_k (E_k - M_k)/M_k$.

    The high-water mark $M_k = \\max(C, \\max_{i \\le k} E_i)$ starts at the
    initial bankroll, so a first-bet loss registers and the ratio stays sane
    after equity crosses zero.
    """
    if equity.size == 0:
        return 0.0
    peak = np.maximum(np.maximum.accumulate(equity), initial_cash)
    drawdown = (equity - peak) / np.where(peak > 0, peak, 1.0)
    return float(drawdown.min())


def per_bet_sharpe(pnl: NDArray[np.float64], initial_cash: float) -> float:
    """Mean over standard deviation of per-bet returns, not annualised.

    Uses ``ddof=1``; a single bet has no dispersion and yields ``0.0``.
    """
    returns = per_bet_returns(pnl, initial_cash)
    if returns.size < 2:
        return 0.0
    std = float(returns.std(ddof=1))
    ratio = float(returns.mean()) / (std + _STD_EPS)
    return ratio if np.isfinite(ratio) else 0.0


@dataclass(frozen=True)
class BetStats:
    """Descriptive statistics of a settled-bet sequence."""

    count: int
    total_return: float
    max_drawdown: float
    per_bet_sharpe: float
    win_rate: float
    profit_factor: float
    max_consecutive_losses: int


def bet_stats(pnl: NDArray[np.float64], initial_cash: float) -> BetStats:
    """Summarise a bet sequence.

    ``profit_factor`` is gross profit over gross loss and is ``0.0`` when there
    is no loss, matching upstream, so a lossless sequence is not reported as
    infinitely good.
    """
    if pnl.size == 0:
        return BetStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    equity = equity_curve(pnl, initial_cash)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_loss = float(-losses.sum())
    profit_factor = float(wins.sum()) / gross_loss if gross_loss > 0 else 0.0

    max_consecutive = 0
    current = 0
    for value in pnl:
        if value < 0:
            current += 1
            max_consecutive = max(max_consecutive, current)
        else:
            current = 0

    return BetStats(
        count=int(pnl.size),
        total_return=float(equity[-1] / initial_cash - 1.0),
        max_drawdown=max_drawdown(equity, initial_cash),
        per_bet_sharpe=per_bet_sharpe(pnl, initial_cash),
        win_rate=float(wins.size / pnl.size),
        profit_factor=profit_factor,
        max_consecutive_losses=max_consecutive,
    )


@dataclass(frozen=True)
class PermutationTest:
    """Result of the Monte Carlo trade-order permutation test."""

    n_simulations: int
    actual_sharpe: float
    actual_max_drawdown: float
    p_value_sharpe: float
    p_value_max_drawdown: float
    simulated_sharpe_p5: float
    simulated_sharpe_p95: float


def permutation_test(
    pnl: NDArray[np.float64], initial_cash: float, *, n_simulations: int, seed: int
) -> PermutationTest:
    """Shuffle the order of bets to test whether the observed path is unusual.

    Null hypothesis: the observed per-bet Sharpe and maximum drawdown are no
    better than those of a random ordering of the same bets. The p-value is
    the fraction of permutations at least as good as the observed path, so it
    measures path dependence (sizing and streak effects), not edge: shuffling
    never changes the final bankroll.

    Raises:
        ValueError: Fewer than three bets or a non-positive simulation count.
    """
    if pnl.size < _MIN_BETS:
        raise ValueError(f"need at least {_MIN_BETS} bets, got {pnl.size}")
    if n_simulations < 1:
        raise ValueError(f"n_simulations must be >= 1, got {n_simulations}")

    actual_sharpe = per_bet_sharpe(pnl, initial_cash)
    actual_dd = max_drawdown(equity_curve(pnl, initial_cash), initial_cash)

    rng = np.random.default_rng(seed)
    sharpes = np.empty(n_simulations, dtype=np.float64)
    drawdowns = np.empty(n_simulations, dtype=np.float64)
    for i in range(n_simulations):
        shuffled = rng.permutation(pnl)
        sharpes[i] = per_bet_sharpe(shuffled, initial_cash)
        drawdowns[i] = max_drawdown(equity_curve(shuffled, initial_cash), initial_cash)

    return PermutationTest(
        n_simulations=n_simulations,
        actual_sharpe=actual_sharpe,
        actual_max_drawdown=actual_dd,
        p_value_sharpe=float(np.mean(sharpes >= actual_sharpe)),
        # A less negative drawdown is better.
        p_value_max_drawdown=float(np.mean(drawdowns >= actual_dd)),
        simulated_sharpe_p5=float(np.percentile(sharpes, 5)),
        simulated_sharpe_p95=float(np.percentile(sharpes, 95)),
    )


@dataclass(frozen=True)
class BootstrapInterval:
    """Bootstrap confidence interval for the per-bet Sharpe ratio."""

    n_bootstrap: int
    confidence: float
    observed: float
    lower: float
    upper: float
    probability_positive: float


def bootstrap_sharpe(
    pnl: NDArray[np.float64],
    initial_cash: float,
    *,
    n_bootstrap: int,
    confidence: float,
    seed: int,
) -> BootstrapInterval:
    """Resample per-bet returns with replacement to bound the Sharpe ratio.

    The interval is the equal-tailed percentile interval at the given
    confidence; ``probability_positive`` is the fraction of resamples with a
    positive ratio.

    Raises:
        ValueError: Fewer than three bets, a non-positive resample count, or a
            confidence outside ``(0, 1)``.
    """
    if pnl.size < _MIN_BETS:
        raise ValueError(f"need at least {_MIN_BETS} bets, got {pnl.size}")
    if n_bootstrap < 1:
        raise ValueError(f"n_bootstrap must be >= 1, got {n_bootstrap}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")

    returns = per_bet_returns(pnl, initial_cash)
    observed = per_bet_sharpe(pnl, initial_cash)

    def ratio(sample: NDArray[np.float64]) -> float:
        std = float(sample.std(ddof=1))
        value = float(sample.mean()) / (std + _STD_EPS)
        return value if np.isfinite(value) else 0.0

    rng = np.random.default_rng(seed)
    samples = np.array(
        [
            ratio(rng.choice(returns, size=returns.size, replace=True))
            for _ in range(n_bootstrap)
        ],
        dtype=np.float64,
    )
    alpha = (1.0 - confidence) / 2.0
    return BootstrapInterval(
        n_bootstrap=n_bootstrap,
        confidence=confidence,
        observed=observed,
        lower=float(np.percentile(samples, alpha * 100.0)),
        upper=float(np.percentile(samples, (1.0 - alpha) * 100.0)),
        probability_positive=float(np.mean(samples > 0)),
    )


@dataclass(frozen=True)
class WalkForwardWindow:
    """Statistics of one contiguous block of bets, normalised to its start."""

    window: int
    first_bet: int
    last_bet: int
    count: int
    total_return: float
    max_drawdown: float
    win_rate: float


@dataclass(frozen=True)
class WalkForward:
    """Consistency of performance across sequential windows of bets."""

    windows: tuple[WalkForwardWindow, ...]
    profitable_windows: int
    consistency_rate: float


def walk_forward(
    pnl: NDArray[np.float64], initial_cash: float, *, n_windows: int
) -> WalkForward:
    """Split the bet sequence into ``n_windows`` contiguous blocks and score each.

    Each block starts from the bankroll it inherits, so a block's return is
    relative to its own starting equity. ``consistency_rate`` is the fraction
    of profitable blocks.

    Raises:
        ValueError: Fewer than two bets per window on average, or a
            non-positive window count.
    """
    if n_windows < 1:
        raise ValueError(f"n_windows must be >= 1, got {n_windows}")
    if pnl.size < 2 * n_windows:
        raise ValueError(f"need at least {2 * n_windows} bets for {n_windows} windows")

    equity = equity_curve(pnl, initial_cash)
    size = pnl.size // n_windows
    windows: list[WalkForwardWindow] = []
    for i in range(n_windows):
        start = i * size
        end = (i + 1) * size if i < n_windows - 1 else pnl.size
        block = pnl[start:end]
        start_equity = float(initial_cash if start == 0 else equity[start - 1])
        block_equity = equity[start:end]
        windows.append(
            WalkForwardWindow(
                window=i + 1,
                first_bet=start,
                last_bet=end - 1,
                count=int(block.size),
                total_return=(
                    float(block_equity[-1] / start_equity - 1.0)
                    if start_equity > 0
                    else 0.0
                ),
                max_drawdown=max_drawdown(block_equity, start_equity),
                win_rate=float(np.mean(block > 0)),
            )
        )
    profitable = sum(1 for w in windows if w.total_return > 0)
    return WalkForward(
        windows=tuple(windows),
        profitable_windows=profitable,
        consistency_rate=profitable / n_windows,
    )
