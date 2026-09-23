"""Edge, fees and position size for a binary contract.

A contract on outcome $A$ trades at a price $q \\in (0, 1)$ and pays 1 if $A$
occurs. With belief $\\hat p$ the expected value of buying one share at the
ask $a$ is $\\hat p - a - \\text{fee}(a)$; betting against $A$ means buying the
complementary share at $1 - b$ (where $b$ is the bid for $A$), worth
$(1 - \\hat p) - (1 - b) - \\text{fee}(1 - b)$.

**Fees.** Polymarket charges a taker fee set per market by the protocol and
applied at match time. Its documentation (trading/fees) and each market's
``feeSchedule`` (read 2026-09-23) give the fee on $C$ shares matched at
price $p$ as

$$\\text{fee} = C \\cdot r \\cdot \\bigl(p (1 - p)\\bigr)^{e},$$

with $r$ the market's taker rate and $e$ its exponent. Sports and weather
markets carried $r = 0.05$, $e = 1$ that day, takers only. The form is
symmetric in $p$ and vanishes at the extremes, so a fee is largest on 50/50
contracts. The rate is read from the market (``BinaryMarket.fee_rate``) and
only a market that does not state one falls back to an assumed rate; see
:func:`fees_for`.

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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vp.markets.schema import BinaryMarket


@dataclass(frozen=True)
class FeeModel:
    """Taker fee per share at price ``p``: ``rate * (p * (1 - p)) ** exponent``."""

    rate: float = 0.0
    exponent: float = 1.0

    def per_share(self, price: float) -> float:
        return self.rate * (price * (1.0 - price)) ** self.exponent


def fees_for(market: BinaryMarket, fallback: FeeModel) -> tuple[FeeModel, str]:
    """The market's own fee model, or ``fallback`` when it states none.

    The second value says which: ``"market"`` or ``"assumed"``.
    """
    if market.fee_rate is None:
        return fallback, "assumed"
    return FeeModel(market.fee_rate, market.fee_exponent), "market"


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


@dataclass(frozen=True)
class Policy:
    """How a belief becomes a position: a strategy's rule and caps.

    The default is the engine's behaviour before strategies (the side with
    edge, fractional Kelly, capped per position), so the backtest and the
    paper loop run unchanged without one. A strategy's spec supplies the
    rest (docs/strategies.md): the sides it may take, the band its price
    must lie in, a ``follow`` rule that makes no forecast and stakes a flat
    fraction on the favourite or the underdog, and caps in dollars, open
    positions and positions per event.
    """

    kelly_multiplier: float = 0.25
    max_fraction: float = 0.05
    min_edge: float = 0.0
    sides: str = "both"  # "both", "yes" or "no"
    follow: str | None = None  # "favourite" or "underdog"
    flat_fraction: float = 0.01
    price_min: float = 0.0
    price_max: float = 1.0
    max_stake_usd: float | None = None
    max_open: int | None = None
    max_per_event: int | None = None

    def position(
        self, p_hat: float, *, ask: float, bid: float, fees: FeeModel
    ) -> Position | None:
        """The position to take at this touch, or ``None``."""
        if self.follow is not None:
            favourite = "yes" if ask + bid >= 1.0 else "no"
            side = favourite if self.follow == "favourite" else _other(favourite)
            fraction = min(self.flat_fraction, self.max_fraction)
            position = Position(side, 0.0, fraction, 0.0)
        else:
            found = size(
                p_hat,
                ask=ask,
                bid=bid,
                fees=fees,
                kelly_multiplier=self.kelly_multiplier,
                max_fraction=self.max_fraction,
                min_edge=self.min_edge,
            )
            if found is None or self.sides not in ("both", found.side):
                return None
            position = found
        quote = ask if position.side == "yes" else 1.0 - bid
        if not self.price_min <= quote <= self.price_max or not 0.0 < quote < 1.0:
            return None
        if self.follow is not None:
            price = quote + fees.per_share(quote)
            return Position(position.side, price, position.fraction, 0.0)
        return position

    def stake(self, fraction: float, bankroll: float, cash: float) -> float:
        """Dollars to stake: the fraction of the bankroll, within cash and cap."""
        stake = min(fraction * bankroll, cash)
        if self.max_stake_usd is not None:
            stake = min(stake, self.max_stake_usd)
        return stake

    def admits(self, open_orders: list[dict], event_id: str | None) -> bool:
        """Whether one more position fits the open-position caps."""
        if self.max_open is not None and len(open_orders) >= self.max_open:
            return False
        if self.max_per_event is not None and event_id is not None:
            same = sum(1 for o in open_orders if o.get("event_id") == event_id)
            if same >= self.max_per_event:
                return False
        return True


def _other(side: str) -> str:
    return "no" if side == "yes" else "yes"
