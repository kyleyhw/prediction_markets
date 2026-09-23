"""The signal contract (plan, task 63; docs/signals.md).

A signal is a function from a market and its cutoff-bounded evidence to the
probability of the market's first outcome, or ``None`` to decline, with
metadata that says where it applies, what evidence it reads, what its
cutoff means, how much history it needs, whether it reads the market's own
price, and whom it follows. :class:`SignalForecaster` makes one a
forecaster, named ``signal:<id>``, so the backtest, the paper loop and a
strategy's belief use it unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from vp.forecast.base import Forecast, clip
from vp.forecast.evidence import Evidence
from vp.markets.schema import BinaryMarket

PREFIX = "signal:"


@dataclass(frozen=True)
class SignalMeta:
    """What a signal is and where it applies."""

    id: str
    title: str
    domains: tuple[str, ...]  # () means every domain
    kinds: tuple[str, ...]  # () means every kind
    accessors: tuple[str, ...]
    cutoff: str
    warmup: str
    references: tuple[str, ...]
    uses_price: bool = False
    licence: str = "method only; the data is the venue's own"
    extra: dict[str, str] = field(default_factory=dict)

    def applies(self, market: BinaryMarket) -> bool:
        return (not self.domains or market.domain in self.domains) and (
            not self.kinds or market.parsed.get("kind") in self.kinds
        )


class Signal(Protocol):
    meta: SignalMeta

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None: ...


@dataclass
class SignalForecaster:
    """A signal as a forecaster."""

    signal: Signal

    @property
    def name(self) -> str:
        return PREFIX + self.signal.meta.id

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        if not self.signal.meta.applies(market):
            return None
        p = self.signal.compute(market, evidence)
        if p is None:
            return None
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(p),
            f"{self.signal.meta.id}: {p:.4f}",
        )


def to_market(
    p_first_wins: float, draw_rate: float, market: BinaryMarket, team_a: str
) -> float:
    """A match market's probability from P(first-listed team wins), the draw
    rate and which side the market asks about (a team, ``draw``, or none for
    a two-team market)."""
    from vp.forecast.evidence import canonical

    side = market.parsed.get("side")
    if side == "draw":
        return draw_rate
    if side is None or canonical(side) == team_a:
        return p_first_wins
    return 1.0 - p_first_wins - draw_rate
