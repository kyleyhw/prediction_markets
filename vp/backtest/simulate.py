"""Event-contract fill simulator: from forecasts and prices to settled bets.

Each market is one round trip. At the cutoff the forecaster holds $\\hat p$
and the market shows a price $q$ for the first outcome. Historical records
carry the last price, not the book, so the touch is reconstructed as
$\\text{bid} = q - s$, $\\text{ask} = q + s$ with a half-spread $s$; snapshots
taken with depth carry the real book and the paper-trading loop uses it
instead. The position is chosen and sized by :func:`vp.backtest.sizing.size`
as a fraction of the bankroll at that moment, filled at the effective price
(fee included), and settled when the market resolves: a share of the
winning side pays 1, the other 0, so the bet's profit is
$\\text{shares} - \\text{stake}$ on a win and $-\\text{stake}$ on a loss. Bets
settle in the order the markets resolved, so the bankroll each one sees is
the bankroll that would actually have been there.

This is a simulator, not the venue: it assumes the whole stake fills at
the touch (a cap of 5% of bankroll keeps stakes small relative to the
books seen in snapshots), ignores partial fills and price impact, and
settles at the label rather than the venue's payout mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass

from vp.backtest.sizing import FeeModel, size


@dataclass(frozen=True)
class Opportunity:
    """One market at its cutoff: forecast, price, and the outcome that followed."""

    market_id: str
    settled: str
    p_hat: float
    q: float
    label: int


@dataclass(frozen=True)
class Bet:
    """A filled and settled position."""

    market_id: str
    settled: str
    side: str
    price: float
    stake: float
    shares: float
    pnl: float
    bankroll_after: float


def simulate(
    opportunities: list[Opportunity],
    *,
    initial_cash: float,
    half_spread: float = 0.01,
    fees: FeeModel = FeeModel(),
    kelly_multiplier: float = 0.25,
    max_fraction: float = 0.05,
) -> list[Bet]:
    """Fill and settle every opportunity with edge, in settlement order."""
    bankroll = initial_cash
    bets: list[Bet] = []
    for opp in sorted(opportunities, key=lambda o: o.settled):
        if bankroll <= 0:
            break
        bid = max(opp.q - half_spread, 0.0)
        ask = min(opp.q + half_spread, 1.0)
        position = size(
            opp.p_hat,
            ask=ask,
            bid=bid,
            fees=fees,
            kelly_multiplier=kelly_multiplier,
            max_fraction=max_fraction,
        )
        if position is None:
            continue
        stake = position.fraction * bankroll
        shares = stake / position.price
        won = opp.label == (1 if position.side == "yes" else 0)
        pnl = shares - stake if won else -stake
        bankroll += pnl
        bets.append(
            Bet(
                opp.market_id,
                opp.settled,
                position.side,
                position.price,
                stake,
                shares,
                pnl,
                bankroll,
            )
        )
    return bets
