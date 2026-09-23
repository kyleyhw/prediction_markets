"""The market's own price, calibrated on the past: Platt and isotonic.

Prices on prediction markets are known to be biased toward long shots in
some sports (the favourite-longshot bias; Snowberg and Wolfers 2010), so
the price read literally is not a calibrated probability. These signals
map the price at the cutoff through a calibration fitted on the domain's
markets settled before the cutoff, each taken at the same distance before
its own settlement (24 hours; `Evidence.settled_prices`), and refit as the
history grows by a tenth.

* **Platt** (Platt 1999): $P(y = 1) = \\sigma(a + b\\,\\mathrm{logit}\\,q)$,
  fitted by Newton's method with a small ridge on $a$ and $b - 1$, so a
  short history leaves the price nearly as it is.
* **Isotonic** (Zadrozny and Elkan 2002): the monotone step function that
  best fits the outcomes by pool-adjacent-violators.

Both read the price, and are judged as corrections of it (F7).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vp.forecast.evidence import Evidence
from vp.markets.schema import BinaryMarket
from vp.signals.base import SignalMeta

HOURS = 24.0
MIN_HISTORY = 200
EPS = 0.01


def _logit(q: float) -> float:
    q = min(max(q, EPS), 1 - EPS)
    return math.log(q / (1 - q))


def _price(market: BinaryMarket, evidence: Evidence) -> float | None:
    q = evidence.price_at(market)
    if q is None and not market.trading_closed:
        q = market.p_yes
    return q


def fit_platt(x: np.ndarray, y: np.ndarray, ridge: float = 1.0) -> tuple[float, float]:
    """(a, b) of the logistic fit, shrunk toward the identity (0, 1)."""
    w = np.array([0.0, 1.0])
    prior = np.array([0.0, 1.0])
    design = np.column_stack([np.ones_like(x), x])
    for _ in range(25):
        p = 1.0 / (1.0 + np.exp(-(design @ w)))
        grad = design.T @ (y - p) - ridge * (w - prior)
        hess = -(design.T * (p * (1 - p))) @ design - ridge * np.eye(2)
        step = np.linalg.solve(hess, grad)
        w = w - step
        if np.max(np.abs(step)) < 1e-8:
            break
    return float(w[0]), float(w[1])


def fit_isotonic(q: np.ndarray, y: np.ndarray) -> tuple[list[float], list[float]]:
    """Block upper bounds and block means of the pool-adjacent-violators fit."""
    order = np.argsort(q)
    qs, ys = q[order], y[order].astype(float)
    blocks: list[list[float]] = []  # [sum, count, upper]
    for qi, yi in zip(qs, ys):
        blocks.append([yi, 1.0, qi])
        while (
            len(blocks) > 1
            and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]
        ):
            s, c, u = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
            blocks[-1][2] = u
    return [b[2] for b in blocks], [b[0] / b[1] for b in blocks]


@dataclass
class CalibratedMarket:
    method: str = "platt"
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="platt_market",
            title="Market price, Platt-calibrated",
            domains=(),
            kinds=(),
            accessors=("price_at", "settled_prices"),
            cutoff="markets settled before the cutoff, each priced 24 hours "
            "before its own settlement",
            warmup=f"{MIN_HISTORY} settled markets with a price",
            references=(
                "Platt, J. (1999). Probabilistic outputs for support vector "
                "machines. Advances in Large Margin Classifiers.",
                "Snowberg, E. and Wolfers, J. (2010). Explaining the "
                "favorite-long shot bias. Journal of Political Economy 118(4).",
            ),
            uses_price=True,
        )
    )
    _fits: dict[str, tuple[int, Any]] = field(default_factory=dict, repr=False)

    def _fit(self, domain: str, evidence: Evidence) -> Any:
        rows = evidence.settled_prices(domain, HOURS)
        if len(rows) < MIN_HISTORY:
            return None
        cached = self._fits.get(domain)
        if (
            cached is not None
            and len(rows) < cached[0] * 1.1
            and len(rows) >= cached[0]
        ):
            return cached[1]
        q = np.array([r[1] for r in rows], dtype=float)
        y = np.array([r[2] for r in rows], dtype=float)
        if self.method == "platt":
            model: Any = fit_platt(np.array([_logit(v) for v in q]), y)
        else:
            model = fit_isotonic(q, y)
        self._fits[domain] = (len(rows), model)
        return model

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        q = _price(market, evidence)
        if q is None:
            return None
        model = self._fit(market.domain or "", evidence)
        if model is None:
            return None
        if self.method == "platt":
            a, b = model
            return 1.0 / (1.0 + math.exp(-(a + b * _logit(q))))
        uppers, means = model
        return float(means[min(bisect_right(uppers, q), len(means) - 1)])


def isotonic_market() -> CalibratedMarket:
    return CalibratedMarket(
        method="isotonic",
        meta=SignalMeta(
            id="isotonic_market",
            title="Market price, isotonic-calibrated",
            domains=(),
            kinds=(),
            accessors=("price_at", "settled_prices"),
            cutoff="markets settled before the cutoff, each priced 24 hours "
            "before its own settlement",
            warmup=f"{MIN_HISTORY} settled markets with a price",
            references=(
                "Zadrozny, B. and Elkan, C. (2002). Transforming classifier "
                "scores into accurate multiclass probability estimates. KDD.",
            ),
            uses_price=True,
        ),
    )
