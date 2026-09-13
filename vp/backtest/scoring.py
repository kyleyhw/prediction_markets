"""Proper scores, skill, and calibration for binary forecasts.

For a forecast $\\hat p$ of an event with outcome $y \\in \\{0, 1\\}$:

* Brier score $(\\hat p - y)^2$, mean over markets $\\overline{BS}$; 0.25 is
  what $\\hat p = 0.5$ earns regardless of outcome.
* Log score $-[y \\ln \\hat p + (1 - y) \\ln(1 - \\hat p)]$; forecasts are
  clipped away from 0 and 1 upstream so it is finite.
* Skill relative to a reference forecast (the market price) is
  $1 - \\overline{BS}/\\overline{BS}_{\\text{ref}}$ on the same markets: positive
  means better than the reference, 0 equal, negative worse.

Both scores are strictly proper: the expected score is minimised only by
reporting one's true belief, so a forecaster gains nothing by hedging toward
the market or away from it. The decomposition below is Murphy's (1973): with
forecasts grouped into $K$ bins with counts $n_k$, mean forecast $\\bar p_k$,
observed frequency $\\bar y_k$ and base rate $\\bar y$,

$$\\overline{BS} = \\text{REL} - \\text{RES} + \\text{UNC}, \\quad
\\text{REL} = \\tfrac1N \\sum_k n_k (\\bar p_k - \\bar y_k)^2, \\quad
\\text{RES} = \\tfrac1N \\sum_k n_k (\\bar y_k - \\bar y)^2, \\quad
\\text{UNC} = \\bar y (1 - \\bar y),$$

exactly when the score is computed with the bin-mean forecasts; with the raw
forecasts a within-bin variance term remains, reported here as the
residual so the identity can be checked. Reliability is calibration error
(lower is better), resolution is how much the forecasts separate outcomes
(higher is better), and uncertainty is the base rate's own entropy, which no
forecaster controls. The reliability diagram is the per-bin table behind it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]


def brier(p: Array, y: Array) -> Array:
    """Per-market Brier score."""
    return (p - y) ** 2


def log_score(p: Array, y: Array) -> Array:
    """Per-market negative log likelihood of the outcome."""
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def skill(score: Array, reference: Array) -> float:
    """$1 - \\overline{s}/\\overline{s}_{\\text{ref}}$ over the same markets."""
    ref = float(reference.mean())
    return 1.0 - float(score.mean()) / ref if ref > 0 else 0.0


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of the reliability diagram."""

    low: float
    high: float
    count: int
    mean_forecast: float
    observed_frequency: float


@dataclass(frozen=True)
class Calibration:
    """Reliability diagram and Murphy decomposition of the Brier score."""

    bins: tuple[ReliabilityBin, ...]
    brier: float
    reliability: float
    resolution: float
    uncertainty: float
    residual: float
    expected_calibration_error: float


def calibration(p: Array, y: Array, *, n_bins: int = 10) -> Calibration:
    """Bin forecasts on equal-width probability intervals and decompose."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    index = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    n = p.size
    base = float(y.mean()) if n else 0.0
    bins: list[ReliabilityBin] = []
    reliability = resolution = ece = 0.0
    for k in range(n_bins):
        mask = index == k
        count = int(mask.sum())
        if count == 0:
            continue
        mean_p = float(p[mask].mean())
        freq = float(y[mask].mean())
        bins.append(ReliabilityBin(edges[k], edges[k + 1], count, mean_p, freq))
        reliability += count * (mean_p - freq) ** 2
        resolution += count * (freq - base) ** 2
        ece += count * abs(mean_p - freq)
    total = float(brier(p, y).mean()) if n else 0.0
    if n:
        reliability, resolution, ece = reliability / n, resolution / n, ece / n
    uncertainty = base * (1 - base)
    return Calibration(
        bins=tuple(bins),
        brier=total,
        reliability=reliability,
        resolution=resolution,
        uncertainty=uncertainty,
        residual=total - (reliability - resolution + uncertainty),
        expected_calibration_error=ece,
    )
