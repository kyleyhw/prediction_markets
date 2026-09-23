"""Blends: signals and the market price, combined by logistic regression
fitted only on the past (plan, task 66; docs/signals.md).

At each cutoff, the training set is every market of the domain settled
before it, each seen at the same distance before its own settlement
(``hours``): the logit of its price then and the logit of each signal's
value then, with its label. The fit is refitted when ``refit_days`` have
passed since the last, and its ridge penalty pulls toward "the market
price, unchanged" (intercept 0, market weight 1, signal weights 0), so a
short history leaves the price as it is. A blend is scored only on markets
settled after its fit, which a backtest's settlement order gives by
construction. It reads the price, so it is judged as a correction of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from vp.forecast.base import Forecast, clip
from vp.forecast.evidence import Evidence, settled_at
from vp.markets.schema import BinaryMarket
from vp.signals import registry
from vp.signals.base import Signal
from vp.signals.market import _logit, _price


def fit_logistic(
    x: np.ndarray, y: np.ndarray, prior: np.ndarray, ridge: float
) -> np.ndarray:
    """Newton's method for a logistic fit with a ridge toward ``prior``."""
    w = prior.copy()
    for _ in range(30):
        p = 1.0 / (1.0 + np.exp(-(x @ w)))
        grad = x.T @ (y - p) - ridge * (w - prior)
        hess = -(x.T * (p * (1 - p))) @ x - ridge * np.eye(len(w))
        step = np.linalg.solve(hess, grad)
        w = w - step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


@dataclass
class Blend:
    signal_ids: tuple[str, ...]
    hours: float = 24.0
    ridge: float = 1.0
    refit_days: int = 30
    min_history: int = 100
    _signals: list[Signal] = field(default_factory=list, repr=False)
    _values: dict[str, list[float] | None] = field(default_factory=dict, repr=False)
    _fits: dict[str, tuple[datetime, np.ndarray]] = field(
        default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        self._signals = [registry.load(i) for i in self.signal_ids]

    @property
    def name(self) -> str:
        return "blend:" + "+".join(self.signal_ids)

    def _features(self, market: BinaryMarket, ev: Evidence) -> list[float] | None:
        q = _price(market, ev)
        if q is None:
            return None
        row = [1.0, _logit(q)]
        for s in self._signals:
            v = s.compute(market, ev) if s.meta.applies(market) else None
            if v is None:
                return None
            row.append(_logit(v))
        return row

    def _fit(self, domain: str, evidence: Evidence) -> np.ndarray | None:
        cached = self._fits.get(domain)
        if cached and evidence.cutoff - cached[0] < timedelta(days=self.refit_days):
            return cached[1]
        rows, labels = [], []
        for m in evidence.settled(domain):
            key = m.market_id or ""
            if key not in self._values:
                when = settled_at(m)
                assert when is not None
                self._values[key] = self._features(
                    m, evidence.at(when - timedelta(hours=self.hours))
                )
            row = self._values[key]
            if row is not None:
                rows.append(row)
                labels.append(float(m.resolved_outcome or 0))
        if len(rows) < self.min_history:
            return None
        prior = np.zeros(len(rows[0]))
        prior[1] = 1.0
        w = fit_logistic(np.array(rows), np.array(labels), prior, self.ridge)
        self._fits[domain] = (evidence.cutoff, w)
        return w

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        x = self._features(market, evidence)
        if x is None:
            return None
        w = self._fit(market.domain or "", evidence)
        if w is None:
            return None
        p = 1.0 / (1.0 + math.exp(-float(np.dot(w, x))))
        weights = ", ".join(f"{v:+.3f}" for v in w)
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(p),
            f"{self.name}: weights (intercept, market, signals) {weights}",
        )
