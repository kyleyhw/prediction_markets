"""Weather signals: climatology, persistence, and the event's own prices.

* **Climatology** (Wilks 2011, ch. 7): the Phase 8 forecaster as a signal,
  the bucket's frequency among observations at the city in the same season
  of earlier years.
* **Persistence**: the day is like the last day observed before the
  cutoff, $v_0$, give or take the city's day-to-day change: with $\\sigma$
  the standard deviation of consecutive-day differences before the cutoff
  and $g$ the days between, the bucket $[l, h]$ (whole degrees) has
  probability $\\Phi((h + \\tfrac12 - v_0)/s) - \\Phi((l - \\tfrac12 - v_0)/s)$
  with $s = \\sigma\\sqrt g$.
* **Bucket normalised**: a day's buckets are mutually exclusive and one
  resolves Yes, so their prices should sum to one; the bucket's price
  divided by the sum of its event's prices at the cutoff. It reads prices,
  and says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from vp.forecast.baselines import Climatology
from vp.forecast.evidence import Evidence, market_date
from vp.markets.schema import BinaryMarket
from vp.signals.base import SignalMeta

BUCKETS = ("daily_temperature",)
WILKS = (
    "Wilks, D. S. (2011). Statistical Methods in the Atmospheric Sciences, "
    "3rd ed., chapter 7. Academic Press.",
)


@dataclass
class ClimatologySignal:
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="climatology",
            title="Climatology",
            domains=(),
            kinds=BUCKETS,
            accessors=("daily_highs",),
            cutoff="observed days before the cutoff",
            warmup="five observations in the season or the last two weeks",
            references=WILKS,
        )
    )
    _inner: Climatology = field(default_factory=Climatology, repr=False)

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        answer = self._inner.forecast(market, evidence)
        return None if answer is None else answer.p_hat


def _bound(text: str) -> float | None:
    return float(text) if text else None


@dataclass
class PersistenceSignal:
    min_diffs: int = 10
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="persistence",
            title="Persistence",
            domains=(),
            kinds=BUCKETS,
            accessors=("daily_highs",),
            cutoff="observed days before the cutoff",
            warmup="ten pairs of consecutive observed days",
            references=WILKS,
        )
    )

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        p = market.parsed
        target = market_date(market)
        if target is None:
            return None
        obs = evidence.daily_highs(p["city"], p.get("statistic", "highest"))
        before = [o for o in obs if o.day < target]
        if not before:
            return None
        diffs = [
            b.value - a.value
            for a, b in zip(before, before[1:])
            if (b.day - a.day).days == 1
        ]
        if len(diffs) < self.min_diffs:
            return None
        mean = sum(diffs) / len(diffs)
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1))
        last = before[-1]
        spread = max(sd, 0.5) * math.sqrt((target - last.day).days)
        low, high = _bound(p.get("low", "")), _bound(p.get("high", ""))

        def cdf(x: float) -> float:
            return 0.5 * (1.0 + math.erf((x - last.value) / (spread * math.sqrt(2))))

        upper = 1.0 if high is None else cdf(high + 0.5)
        lower = 0.0 if low is None else cdf(low - 0.5)
        return max(upper - lower, 0.0)


@dataclass
class BucketNormalisedSignal:
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="bucket_normalised",
            title="Bucket prices normalised",
            domains=(),
            kinds=BUCKETS,
            accessors=("price_at", "event_prices"),
            cutoff="the event's prices at the cutoff",
            warmup="none; needs every bucket of the day priced",
            references=(
                "Cross-market consistency: the buckets of a negative-risk event "
                "are exclusive and exhaustive, so their prices sum to one.",
            ),
            uses_price=True,
        )
    )

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        siblings = evidence.event_prices(market)
        prices = [q for _, q in siblings]
        own = next((q for m, q in siblings if m.market_id == market.market_id), None)
        if own is None or len(prices) < 2 or any(q is None for q in prices):
            return None
        total = sum(q for q in prices if q is not None)
        return own / total if total > 0 else None
