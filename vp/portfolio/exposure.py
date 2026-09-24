"""Open positions as a portfolio (docs/portfolio.md, task 98).

Positions settle together and are correlated within events. The joint
model: a negative-risk event's markets are mutually exclusive (one
categorical draw, with an "other" outcome for what is not held); other
markets of one event share a Gaussian copula with correlation
``EVENT_RHO``; markets of one domain resolving on one day share a common
factor ``DAY_RHO``. Probabilities are the market's prices, not the
strategy's belief. The worst case is exact; quantiles come from the draws.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import NormalDist
from typing import Any

import numpy as np

EVENT_RHO, DAY_RHO = 0.5, 0.1
DRAWS = 20_000
EPS = 1e-6


@dataclass(frozen=True)
class Position:
    market_id: str
    event_id: str | None
    side: str  # "yes" (the first outcome) or "no"
    shares: float
    stake: float
    p_first: float  # the first outcome's probability (price, or belief)
    domain: str | None = None
    end: datetime | None = None
    neg_risk: bool = False
    strategy: str | None = None

    @property
    def event(self) -> str:
        return self.event_id or f"market:{self.market_id}"

    @property
    def day(self) -> str:
        return self.end.date().isoformat() if self.end else "undated"


def _events(positions: Sequence[Position]) -> dict[str, list[str]]:
    """Each event's distinct markets, in order."""
    out: dict[str, list[str]] = defaultdict(list)
    for p in positions:
        if p.market_id not in out[p.event]:
            out[p.event].append(p.market_id)
    return out


def exclusive(positions: Sequence[Position], markets: list[str]) -> bool:
    flags = {p.market_id: p.neg_risk for p in positions if p.market_id in markets}
    return len(markets) > 1 and all(flags.values())


def draw(
    positions: Sequence[Position],
    n: int = DRAWS,
    seed: int = 0,
    event_rho: float = EVENT_RHO,
    day_rho: float = DAY_RHO,
) -> tuple[list[str], np.ndarray]:
    """Joint outcomes: the market ids and an ``n`` by markets matrix, True
    where the first outcome won."""
    rng = np.random.default_rng(seed)
    probs = {p.market_id: min(max(p.p_first, EPS), 1 - EPS) for p in positions}
    meta = {p.market_id: p for p in positions}
    ids = list(probs)
    col = {m: i for i, m in enumerate(ids)}
    won = np.zeros((n, len(ids)), dtype=bool)
    days = {
        d: rng.standard_normal(n) for d in {(m.domain, m.day) for m in meta.values()}
    }
    inv = NormalDist().inv_cdf
    for markets in _events(positions).values():
        if exclusive(positions, markets):
            p = np.array([probs[m] for m in markets])
            if p.sum() > 1:
                p = p / p.sum()
            weights = np.append(p, max(1 - p.sum(), 0.0))
            pick = rng.choice(len(weights), size=n, p=weights / weights.sum())
            for i, m in enumerate(markets):
                won[:, col[m]] = pick == i
            continue
        shared = rng.standard_normal(n) if len(markets) > 1 else np.zeros(n)
        rho_e = event_rho if len(markets) > 1 else 0.0
        for m in markets:
            day = days[(meta[m].domain, meta[m].day)]
            own = np.sqrt(max(1 - rho_e - day_rho, 0.0))
            z = (
                np.sqrt(rho_e) * shared
                + np.sqrt(day_rho) * day
                + own * rng.standard_normal(n)
            )
            won[:, col[m]] = z < inv(probs[m])
    return ids, won


def pnl(positions: Sequence[Position], ids: list[str], won: np.ndarray) -> np.ndarray:
    """Each draw's P&L at settlement: payouts less stakes."""
    col = {m: i for i, m in enumerate(ids)}
    out = np.zeros(won.shape[0])
    for p in positions:
        wins = (
            won[:, col[p.market_id]] if p.side == "yes" else ~won[:, col[p.market_id]]
        )
        out += np.where(wins, p.shares, 0.0) - p.stake
    return out


def worst_case(positions: Sequence[Position]) -> float:
    """The exact worst P&L at settlement."""
    total = 0.0
    for markets in _events(positions).values():
        held = [p for p in positions if p.market_id in markets]
        if exclusive(positions, markets):
            # One of the event's markets wins, or none of those held.
            outcomes = [*markets, None]
            total += min(
                sum(
                    (p.shares if (p.side == "yes") == (p.market_id == w) else 0.0)
                    - p.stake
                    for p in held
                )
                for w in outcomes
            )
            continue
        for m in markets:
            here = [p for p in held if p.market_id == m]
            total += min(
                sum(
                    (p.shares if (p.side == "yes") == first else 0.0) - p.stake
                    for p in here
                )
                for first in (True, False)
            )
    return total


def favourites_win(positions: Sequence[Position]) -> float:
    """The P&L if every favourite wins (in an exclusive event, the likeliest)."""
    total = 0.0
    for markets in _events(positions).values():
        held = [p for p in positions if p.market_id in markets]
        if exclusive(positions, markets):
            price = {p.market_id: p.p_first for p in held}
            winner = max(markets, key=lambda m: price[m])
            total += sum(
                (p.shares if (p.side == "yes") == (p.market_id == winner) else 0.0)
                - p.stake
                for p in held
            )
            continue
        for p in held:
            first = p.p_first >= 0.5
            total += (p.shares if (p.side == "yes") == first else 0.0) - p.stake
    return total


def _shares(positions: Iterable[Position], key: Any) -> list[dict[str, Any]]:
    stake: dict[str, float] = defaultdict(float)
    for p in positions:
        stake[str(key(p))] += p.stake
    total = sum(stake.values()) or EPS
    return [
        {"group": k, "stake": round(v, 2), "share": v / total}
        for k, v in sorted(stake.items(), key=lambda kv: -kv[1])
    ]


def report(
    positions: Sequence[Position], bankroll: float | None = None, seed: int = 0
) -> dict[str, Any]:
    """The exposure of a set of open positions."""
    if not positions:
        return {"positions": 0, "stake": 0.0}
    ids, won = draw(positions, seed=seed)
    sims = pnl(positions, ids, won)
    loss95, loss99 = -np.quantile(sims, 0.05), -np.quantile(sims, 0.01)
    tail = sims[sims <= np.quantile(sims, 0.05)]
    out = {
        "positions": len(positions),
        "stake": round(sum(p.stake for p in positions), 2),
        "expected": float(sims.mean()),
        "worst_case": worst_case(positions),
        "loss_95": float(loss95),
        "loss_99": float(loss99),
        "shortfall_95": float(-tail.mean()) if tail.size else None,
        "favourites_win": favourites_win(positions),
        "by_event": _shares(positions, lambda p: p.event)[:10],
        "by_domain": _shares(positions, lambda p: p.domain or "other"),
        "by_date": _shares(positions, lambda p: p.day),
        "by_strategy": _shares(positions, lambda p: p.strategy or "?"),
        "model": {"event_rho": EVENT_RHO, "day_rho": DAY_RHO, "draws": DRAWS},
    }
    if bankroll:
        out["worst_case_share"] = -out["worst_case"] / bankroll
    return out
