"""Combinatorial positions (docs/portfolio.md, task 103): a conjunction
priced against its legs. Assessed and recorded; nothing here trades."""

from __future__ import annotations

from typing import Any


def assess(conjunction: float, legs: list[float]) -> dict[str, Any]:
    """Where a conjunction's price sits against its legs' prices: the
    Fréchet bounds, the independence price and the implied dependence."""
    low = max(0.0, sum(legs) - (len(legs) - 1))
    high = min(legs)
    independent = 1.0
    for p in legs:
        independent *= p
    return {
        "price": conjunction,
        "bounds": [low, high],
        "independent": independent,
        "implied_dependence": conjunction - independent,
        "consistent": low - 1e-9 <= conjunction <= high + 1e-9,
    }
