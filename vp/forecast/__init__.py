"""Forecasters: given a market and an information cutoff, a probability.

Every forecaster reads the world only through :class:`vp.forecast.evidence.Evidence`,
which is constructed with the cutoff and refuses to serve anything after it;
that single choke point is the look-ahead safeguard the plan calls for.
"""

from __future__ import annotations

from typing import Any

from vp.forecast.base import Forecast, Forecaster
from vp.forecast.baselines import Climatology, Constant, MarketPrice
from vp.forecast.evidence import Evidence
from vp.forecast.stats import Elo

FORECASTER_NAMES = ("market", "constant", "climatology", "elo", "llm")


def make_forecaster(name: str, domain: str, **options: Any) -> Forecaster:
    """Build a forecaster by name for a domain; ``llm`` options pass through."""
    if name == "market":
        return MarketPrice()
    if name == "constant":
        return Constant()
    if name == "climatology":
        return Climatology()
    if name == "elo":
        return Elo(domain, home=60.0 if domain == "epl" else 0.0)
    if name == "llm":
        from vp.forecast.llm import LLMForecaster

        return LLMForecaster(**options)
    raise ValueError(f"unknown forecaster {name!r}; choose from {FORECASTER_NAMES}")


__all__ = [
    "FORECASTER_NAMES",
    "Evidence",
    "Forecast",
    "Forecaster",
    "make_forecaster",
]
