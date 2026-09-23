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


def forecaster_names() -> tuple[str, ...]:
    """Every name a belief may use: the forecasters above and each
    registered signal as ``signal:<id>`` (docs/signals.md)."""
    from vp.signals.registry import ids

    return FORECASTER_NAMES + tuple(f"signal:{i}" for i in ids())


def known(name: str) -> bool:
    """Whether a belief name can be built: a forecaster, a signal, or a blend
    of signals written ``blend:<id>+<id>`` (docs/signals.md)."""
    if name.startswith("blend:"):
        from vp.signals.registry import ids

        parts = name.removeprefix("blend:").split("+")
        return bool(parts) and all(p in ids() for p in parts)
    if name.startswith("committee:"):
        from vp.signals.committee import presets

        return name.removeprefix("committee:") in presets()
    return name in forecaster_names()


def make_forecaster(name: str, domain: str, **options: Any) -> Forecaster:
    """Build a forecaster by name for a domain; ``llm`` options pass through."""
    if name.startswith("blend:"):
        from vp.signals.blend import Blend

        return Blend(tuple(name.removeprefix("blend:").split("+")))
    if name.startswith("committee:"):
        from vp.signals.committee import Committee

        return Committee.preset(name.removeprefix("committee:"), **options)
    if name.startswith("signal:"):
        from vp.signals.base import SignalForecaster
        from vp.signals.registry import load

        return SignalForecaster(load(name.removeprefix("signal:")))
    if name == "market":
        return MarketPrice()
    if name == "constant":
        return Constant()
    if name == "climatology":
        return Climatology()
    if name == "elo":
        from vp.domains import DOMAINS

        home = DOMAINS[domain].home_first if domain in DOMAINS else False
        return Elo(domain, home=60.0 if home else 0.0)
    if name == "llm":
        from vp.forecast.llm import LLMForecaster

        return LLMForecaster(**options)
    raise ValueError(f"unknown forecaster {name!r}; choose from {FORECASTER_NAMES}")


__all__ = [
    "FORECASTER_NAMES",
    "forecaster_names",
    "known",
    "Evidence",
    "Forecast",
    "Forecaster",
    "make_forecaster",
]
