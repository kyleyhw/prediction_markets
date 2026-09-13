"""Edge, fees and position size for a binary contract.

A contract on outcome $A$ trades at a price $q \\in (0, 1)$ and pays 1 if $A$
occurs. With belief $\\hat p$ the expected value of buying one share at the
ask $a$ is $\\hat p - a - \\text{fee}(a)$; betting against $A$ means buying the
complementary share at $1 - b$ (where $b$ is the bid for $A$), worth
$(1 - \\hat p) - (1 - b) - \\text{fee}(1 - b)$.

**Fees.** Polymarket charges a taker fee on some markets, set per market by
the protocol and applied at match time. Its documentation (trading/fees,
read 2026-09-13) gives the fee on $C$ shares matched at price $p$ as

$$\\text{fee} = C \\cdot r \\cdot p (1 - p),$$

with $r$ the market's taker fee rate (``taker_base_fee`` on the CLOB market
object, in basis points). The form is symmetric in $p$ and vanishes at the
extremes, so a fee is largest on 50/50 contracts. Most sports and weather
markets carried $r = 0$ when this was written; the rate is a parameter here
and the live figure must be read from the market, never assumed.

**Kelly.** Buying a share at price $a$ with win probability $\\hat p$ is a bet
at fractional odds $b = (1 - a)/a$: a stake $a$ returns $1$. The Kelly
fraction of bankroll is $f^* = \\hat p - (1 - \\hat p)/b = (\\hat p - a)/(1 - a)$,
positive exactly when there is edge. For the complementary share the same
expression holds with $\\hat p \\to 1 - \\hat p$ and $a \\to 1 - b$, giving
$(b - \\hat p)/b$. Full Kelly maximises the long-run growth rate but its
variance is severe and its optimality assumes $\\hat p$ is exact, so a
fraction of it (a quarter by default) is used; with a mis-estimated $\\hat p$
fractional Kelly gives up little growth for a large reduction in drawdown.
Fees enter through the effective price $a' = a + \\text{fee}(a)$.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeModel:
    """Taker fee per share at price ``p``: ``rate * p * (1 - p)``."""

    rate: float = 0.0

    def per_share(self, price: float) -> float:
        return self.rate * price * (1.0 - price)


@dataclass(frozen=True)
class Position:
    """A sized position: which share to buy, at what effective price, how much."""

    side: str  # "yes" (first outcome) or "no" (second outcome)
    price: float  # effective price paid per share, fee included
    fraction: float  # fraction of bankroll to stake
    edge: float  # expected value per dollar staked


def kelly_fraction(p: float, price: float) -> float:
    """Full Kelly fraction for a share paying 1 with probability ``p`` at ``price``."""
    if price <= 0.0 or price >= 1.0:
        return 0.0
    return max((p - price) / (1.0 - price), 0.0)


def size(
    p_hat: float,
    *,
    ask: float,
    bid: float,
    fees: FeeModel = FeeModel(),
    kelly_multiplier: float = 0.25,
    max_fraction: float = 0.05,
    min_edge: float = 0.0,
) -> Position | None:
    """Choose the side with positive expected value and size it by fractional Kelly.

    Args:
        p_hat: Belief that the first outcome occurs.
        ask: Ask price of the first outcome's share.
        bid: Bid price of the first outcome's share (the complementary share
            is bought at ``1 - bid``).
        fees: Taker fee model.
        kelly_multiplier: Fraction of full Kelly to stake.
        max_fraction: Hard cap on the fraction of bankroll per position.
        min_edge: Smallest probability edge over the effective price worth
            a position. Zero bets on every market outside the spread, which
            a noisy forecaster turns into a stream of coin flips against the
            spread; a few points of required edge filters that.

    Returns:
        The position, or ``None`` when neither side has enough edge after fees.
    """
    yes_price = ask + fees.per_share(ask)
    no_price = (1.0 - bid) + fees.per_share(1.0 - bid)
    yes_edge = p_hat - yes_price
    no_edge = (1.0 - p_hat) - no_price
    if max(yes_edge, no_edge) <= max(min_edge, 0.0):
        return None
    if yes_edge >= no_edge:
        side, price, p = "yes", yes_price, p_hat
    else:
        side, price, p = "no", no_price, 1.0 - p_hat
    fraction = min(kelly_multiplier * kelly_fraction(p, price), max_fraction)
    if fraction <= 0.0:
        return None
    return Position(side, price, fraction, edge=(p - price) / price)
