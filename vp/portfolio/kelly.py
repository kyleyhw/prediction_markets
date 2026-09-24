"""Simultaneous Kelly (docs/portfolio.md, task 99).

Per-bet Kelly sizes each position as if it were the only one. On a
negative-risk event (one bucket of a weather day, one result of a match)
at most one of several positions can win, so per-bet fractions overstate
what the event can bear. Here the fractions of positions open together
maximise expected log growth over their joint outcomes under the belief:
full Kelly with the fractions non-negative and summing to at most one,
then the engine's fractional multiplier and caps, in the engine's order.
Exclusive events are enumerated exactly; others use the exposure model's
draws.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from vp.backtest.sizing import FeeModel, size

RUIN = float(np.log(1e-6))


@dataclass(frozen=True)
class Leg:
    """One market of an event, as the backtest saw it at the cutoff."""

    p_hat: float  # the belief's probability of the first outcome
    ask: float
    bid: float
    fees: FeeModel
    won_first: bool


def _simplex(v: np.ndarray) -> np.ndarray:
    """Euclidean projection onto {f >= 0, sum f <= 1}."""
    f = np.clip(v, 0, None)
    if f.sum() <= 1:
        return f
    u = np.sort(v)[::-1]
    css = np.cumsum(u)
    k = np.nonzero(u * np.arange(1, v.size + 1) > css - 1)[0][-1]
    theta = (css[k] - 1) / (k + 1)
    return np.clip(v - theta, 0, None)


def full_kelly(R: np.ndarray, weights: np.ndarray, iters: int = 2_000) -> np.ndarray:
    """argmax sum_s w_s log(1 + R_s . f) over {f >= 0, sum f <= 1}."""
    f = np.zeros(R.shape[1])
    step = 0.5
    value = 0.0
    for _ in range(iters):
        growth = 1 + R @ f
        g = (weights[:, None] * R / growth[:, None]).sum(0)
        while step > 1e-9:
            nxt = _simplex(f + step * g)
            ok = 1 + R @ nxt
            if (ok > 0).all():
                v = float(weights @ np.log(ok))
                if v >= value - 1e-12:
                    break
            step /= 2
        else:
            break
        if np.abs(nxt - f).max() < 1e-9:
            f = nxt
            break
        f, value = nxt, v
        step = min(step * 1.5, 1.0)
    return f


def capped(
    f: np.ndarray, multiplier: float, max_fraction: float, max_event: float
) -> np.ndarray:
    """The engine's order: multiplier, then the per-position cap, then the
    event's cap (scaling the event's fractions down together)."""
    out = np.minimum(f * multiplier, max_fraction)
    if out.sum() > max_event:
        out *= max_event / out.sum()
    return out


def _scenarios(legs: Sequence[Leg], exclusive: bool, n: int, seed: int):
    """Joint outcomes of the first outcomes under the belief, with weights."""
    p = np.clip(np.array([leg.p_hat for leg in legs]), 1e-6, 1 - 1e-6)
    if exclusive:
        q = p / p.sum() if p.sum() > 1 else p
        other = max(1 - q.sum(), 0.0)
        won = np.vstack([np.eye(len(legs), dtype=bool), np.zeros((1, len(legs)), bool)])
        return won, np.append(q, other)
    rng = np.random.default_rng(seed)
    from statistics import NormalDist

    from vp.portfolio.exposure import EVENT_RHO

    rho = EVENT_RHO if len(legs) > 1 else 0.0
    shared = rng.standard_normal(n)
    z = np.sqrt(rho) * shared[:, None] + np.sqrt(1 - rho) * rng.standard_normal(
        (n, len(legs))
    )
    cut = np.array([NormalDist().inv_cdf(x) for x in p])
    return z < cut, np.full(n, 1.0 / n)


def compare_event(
    legs: Sequence[Leg],
    exclusive: bool,
    *,
    multiplier: float = 0.25,
    max_fraction: float = 0.05,
    max_event: float = 0.10,
    min_edge: float = 0.0,
    n: int = 4_000,
    seed: int = 0,
) -> dict[str, Any] | None:
    """Per-bet against simultaneous Kelly on one event's realised outcome."""
    picks = []
    for leg in legs:
        pos = size(
            leg.p_hat,
            ask=leg.ask,
            bid=leg.bid,
            fees=leg.fees,
            kelly_multiplier=multiplier,
            max_fraction=max_fraction,
            min_edge=min_edge,
        )
        if pos is not None and 0 < pos.price < 1:
            picks.append((leg, pos))
    if not picks:
        return None
    won, weights = _scenarios([leg for leg, _ in picks], exclusive, n, seed)
    yes = np.array([pos.side == "yes" for _, pos in picks])
    price = np.array([pos.price for _, pos in picks])
    R = np.where(won == yes, 1.0, 0.0) / price - 1
    joint = capped(full_kelly(R, weights), multiplier, max_fraction, max_event)
    single = np.array([pos.fraction for _, pos in picks])
    actual = np.array([(leg.won_first == (pos.side == "yes")) for leg, pos in picks])
    r = np.where(actual, 1.0, 0.0) / price - 1

    def growth(f: np.ndarray) -> float:
        g = 1 + float(r @ f)
        return float(np.log(g)) if g > 0 else RUIN

    return {
        "positions": len(picks),
        "per_bet": {"total": float(single.sum()), "growth": growth(single)},
        # The same with only the event cap added, to separate the cap's
        # effect from the joint optimisation's.
        "per_bet_capped": {
            "total": float(min(single.sum(), max_event)),
            "growth": growth(capped(single, 1.0, max_fraction, max_event)),
        },
        "joint": {"total": float(joint.sum()), "growth": growth(joint)},
    }
