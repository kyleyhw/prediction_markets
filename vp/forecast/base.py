"""The forecaster contract.

A forecast is a probability $\\hat p$ that the market's first outcome occurs,
made at an information cutoff $t$ from evidence available before $t$, with
the rationale that produced it and what it cost. ``None`` from a forecaster
means it declines the market (no price at the cutoff, an unparsed question,
no evidence), which the backtest records as a skip rather than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from vp.forecast.evidence import Evidence
from vp.markets.schema import BinaryMarket

# Probabilities are clipped away from 0 and 1 so the log score is finite and a
# single confident miss cannot dominate a mean; 1% is the conventional floor.
P_FLOOR = 0.01


def clip(p: float) -> float:
    """Clip a probability into ``[P_FLOOR, 1 - P_FLOOR]``."""
    return min(max(p, P_FLOOR), 1.0 - P_FLOOR)


@dataclass(frozen=True)
class Forecast:
    """One forecaster's probability for one market at one cutoff."""

    market_id: str | None
    forecaster: str
    cutoff: str
    p_hat: float
    rationale: str
    cost_usd: float = 0.0
    meta: dict[str, str] = field(default_factory=dict)


class Forecaster(Protocol):
    """Anything that turns a market plus cutoff-bounded evidence into a forecast."""

    @property
    def name(self) -> str:
        """Short name used in the registry and reports."""
        ...

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        """Return a forecast, or ``None`` to decline the market."""
        ...
