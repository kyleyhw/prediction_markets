"""Baseline forecasters: the market itself, ignorance, and climatology.

* ``MarketPrice`` returns the market's own price at the cutoff, $q$: the
  stored history point at the cutoff in a backtest, or the snapshot price
  itself for a market still trading (the forward loop, where the snapshot
  is the present). It is the baseline every other forecaster is scored
  against: a forecaster with skill must beat it on a proper score over the
  same markets.
* ``Constant`` returns a fixed probability, 0.5 by default; it anchors the
  scale (a Brier score of 0.25 is what knowing nothing earns).
* ``Climatology`` answers a daily-temperature bucket question with the
  empirical frequency of that bucket among realised highs at the same city
  on nearby calendar days in earlier years, falling back to the most recent
  days when there is no earlier year. Laplace smoothing keeps it off 0 and 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from vp.forecast.base import Forecast, clip
from vp.forecast.evidence import Evidence, market_date
from vp.markets.schema import BinaryMarket


@dataclass(frozen=True)
class MarketPrice:
    """The market's implied probability at the cutoff."""

    name: str = "market"

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        q = evidence.price_at(market)
        if q is None and not market.trading_closed:
            q = market.p_yes
        if q is None:
            return None
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(q),
            f"market price at cutoff: {q:.3f}",
        )


@dataclass(frozen=True)
class Constant:
    """A fixed probability."""

    p: float = 0.5
    name: str = "constant"

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(self.p),
            f"constant {self.p}",
        )


def in_bucket(value: float, low: float | None, high: float | None) -> bool:
    """Whether a temperature lies in an inclusive bucket with optional open ends."""
    return (low is None or value >= low) and (high is None or value <= high)


@dataclass(frozen=True)
class Climatology:
    """Empirical bucket frequency from earlier observations at the same city.

    Args:
        window_days: Half-width of the calendar window around the target day
            in earlier years.
        recent_days: Fallback window of the most recent days before the
            cutoff when no earlier year is available.
        min_obs: Below this many observations the forecaster declines.
    """

    window_days: int = 15
    recent_days: int = 14
    min_obs: int = 5
    name: str = "climatology"

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        p = market.parsed
        target = market_date(market)
        if p.get("kind") != "daily_temperature" or target is None:
            return None
        obs = evidence.daily_highs(p["city"], p.get("statistic", "highest"))
        same_season = [
            o
            for o in obs
            if o.day.year < target.year
            and abs((o.day.replace(year=target.year) - target).days) <= self.window_days
        ]
        basis = "earlier years, same season"
        if len(same_season) < self.min_obs:
            since = evidence.cutoff.date() - timedelta(days=self.recent_days)
            same_season = [o for o in obs if o.day >= since]
            basis = f"last {self.recent_days} days"
        if len(same_season) < self.min_obs:
            return None
        low, high = _bound(p.get("low", "")), _bound(p.get("high", ""))
        hits = sum(in_bucket(o.value, low, high) for o in same_season)
        p_hat = (hits + 1) / (len(same_season) + 2)
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(p_hat),
            f"{hits} of {len(same_season)} observations ({basis}) in bucket "
            f"[{p.get('low') or '-inf'}, {p.get('high') or 'inf'}] {p.get('unit', '')}",
        )


def _bound(text: str) -> float | None:
    return float(text) if text else None
