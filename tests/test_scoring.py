"""Scores and the Murphy decomposition on hand-checkable forecasts."""

from __future__ import annotations

import numpy as np
import pytest

from vp.backtest.scoring import brier, calibration, log_score, skill


def test_scores_on_known_values() -> None:
    p = np.array([0.5, 0.9, 0.1, 0.9])
    y = np.array([1.0, 1.0, 0.0, 0.0])
    assert brier(p, y).tolist() == pytest.approx([0.25, 0.01, 0.01, 0.81])
    assert log_score(p, y)[0] == pytest.approx(np.log(2))
    assert log_score(p, y)[3] == pytest.approx(-np.log(0.1))
    # A constant 0.5 forecast scores 0.25 everywhere; halving it is skill 0.5.
    half = np.full(4, 0.25)
    assert skill(np.full(4, 0.125), half) == 0.5
    assert skill(half, half) == 0.0
    assert skill(half, np.zeros(4)) == 0.0


def test_murphy_decomposition_identity() -> None:
    rng = np.random.default_rng(0)
    p = rng.uniform(0.01, 0.99, 500)
    y = (rng.uniform(size=500) < p).astype(float)  # calibrated by construction
    cal = calibration(p, y, n_bins=10)
    # Brier = REL - RES + UNC + residual, and the residual is the within-bin
    # variance of the forecasts, which is non-negative.
    assert cal.brier == pytest.approx(
        cal.reliability - cal.resolution + cal.uncertainty + cal.residual
    )
    assert cal.residual >= 0
    assert cal.reliability < 0.01  # calibrated forecasts have small reliability
    assert sum(b.count for b in cal.bins) == 500
    assert all(b.low <= b.mean_forecast <= b.high for b in cal.bins)
    assert cal.uncertainty == pytest.approx(y.mean() * (1 - y.mean()))


def test_calibration_with_bin_means_is_exact_and_handles_empty() -> None:
    # Two bins, all forecasts at their bin means: residual is exactly zero.
    p = np.array([0.2, 0.2, 0.8, 0.8])
    y = np.array([0.0, 1.0, 1.0, 1.0])
    cal = calibration(p, y, n_bins=5)
    assert cal.residual == pytest.approx(0.0)
    assert len(cal.bins) == 2 and cal.bins[0].observed_frequency == 0.5
    assert cal.expected_calibration_error == pytest.approx((2 * 0.3 + 2 * 0.2) / 4)
    empty = calibration(np.array([]), np.array([]))
    assert empty.bins == () and empty.brier == 0.0
