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
from datetime import date

from vp.forecast.baselines import Climatology
from vp.forecast.evidence import Evidence, NwpDay, market_date
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


def _in_unit(celsius: float, unit: str) -> float:
    return celsius * 9 / 5 + 32 if unit == "°F" else celsius


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def _station_errors(
    market: BinaryMarket, evidence: Evidence, lead: int
) -> tuple[dict[date, NwpDay], list[float]]:
    """The station's forecasts by day at ``lead``, and the errors (observed
    minus forecast, in the question's unit) on earlier settled days whose
    bucket was closed, most recent last."""
    p = market.parsed
    stat, unit = p.get("statistic", "highest"), p["unit"]
    days = {d.day: d for d in evidence.nwp(market) if d.lead_days == lead}
    errors = []
    for o in evidence.daily_highs(p["city"], stat):
        fc = days.get(o.day)
        if fc is not None and o.low is not None and o.high is not None:
            value = fc.tmax if stat == "highest" else fc.tmin
            errors.append(o.value - _in_unit(value, unit))
    return days, errors


def _bucket_edges(market: BinaryMarket) -> tuple[float | None, float | None]:
    low, high = _bound(market.parsed.get("low", "")), _bound(market.parsed["high"])
    return (
        None if low is None else low - 0.5,
        None if high is None else high + 0.5,
    )


NWP_REFERENCES = (
    "Open-Meteo Previous Runs API: forecasts as issued, archived from 2024.",
    "Wilks, D. S. (2011). Statistical Methods in the Atmospheric Sciences, "
    "3rd ed., chapter 7 (model output statistics).",
)


@dataclass
class NwpForecastSignal:
    """The bucket's probability under the numerical forecast issued before the
    cutoff, corrected by the station's own recent error distribution: the
    forecast $f$ with the newest lead visible, errors $e$ of the same lead on
    earlier settled days, and the bucket $[l, h]$ given probability
    $\\Phi((h + \\tfrac12 - f - \\bar e)/s)
    - \\Phi((l - \\tfrac12 - f - \\bar e)/s)$."""

    min_pairs: int = 15
    window: int = 60
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="nwp_forecast",
            title="Weather model forecast",
            domains=(),
            kinds=BUCKETS,
            accessors=("nwp", "daily_highs"),
            cutoff="forecasts that existed before the cutoff; observed days before it",
            warmup="fifteen earlier settled days at the station with a forecast",
            references=NWP_REFERENCES,
            licence="Open-Meteo data, CC BY 4.0; paid plan in production (F9)",
        )
    )

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        target = market_date(market)
        if target is None:
            return None
        leads = sorted({d.lead_days for d in evidence.nwp(market) if d.day == target})
        if not leads:
            return None
        days, errors = _station_errors(market, evidence, leads[0])
        errors = errors[-self.window :]
        if len(errors) < self.min_pairs:
            return None
        stat, unit = market.parsed.get("statistic", "highest"), market.parsed["unit"]
        fc = days[target]
        mean = sum(errors) / len(errors)
        centre = _in_unit(fc.tmax if stat == "highest" else fc.tmin, unit) + mean
        spread = max(
            math.sqrt(sum((e - mean) ** 2 for e in errors) / (len(errors) - 1)), 0.5
        )
        low, high = _bucket_edges(market)
        upper = 1.0 if high is None else _normal_cdf((high - centre) / spread)
        lower = 0.0 if low is None else _normal_cdf((low - centre) / spread)
        return min(max(upper - lower, 0.0), 1.0)


@dataclass
class NwpEnsembleSignal:
    """The share of ensemble members in the bucket, each shifted by the
    station's mean error at lead one, with one pseudo-member split evenly."""

    min_pairs: int = 15
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="nwp_ensemble",
            title="Weather ensemble",
            domains=(),
            kinds=BUCKETS,
            accessors=("ensemble", "nwp", "daily_highs"),
            cutoff="the newest ensemble captured before the cutoff",
            warmup="an ensemble captured for the day; fifteen settled days",
            references=NWP_REFERENCES,
            licence="Open-Meteo data, CC BY 4.0; paid plan in production (F9)",
        )
    )

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        members = evidence.ensemble(market)
        if not members:
            return None
        _, errors = _station_errors(market, evidence, 1)
        if len(errors) < self.min_pairs:
            return None
        shift = sum(errors[-60:]) / len(errors[-60:])
        stat, unit = market.parsed.get("statistic", "highest"), market.parsed["unit"]
        low, high = _bucket_edges(market)
        hits = 0
        for tmax, tmin in members:
            raw = tmax if stat == "highest" else tmin
            if raw is None:
                continue
            v = _in_unit(raw, unit) + shift
            hits += (low is None or v >= low) and (high is None or v < high)
        return (hits + 0.5) / (len(members) + 1)
