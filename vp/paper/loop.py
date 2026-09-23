"""The forward paper-trading loop and its settlement pass.

One cycle of :func:`run_cycle`:

1. Snapshot the domain's open markets with book depth (the same collector
   the data layer uses, so the snapshot files accumulate as before).
2. Build the evidence view at *now*: the resolved sets give results and
   observations up to the present, and nothing after it exists yet, so the
   forward loop cannot look ahead by construction. Its scores are therefore
   the honest counterpart of the backtest's; Phase 10's leakage check
   compares the two.
3. Ask each forecaster for every parsed market it accepts. A forecast that
   is the forecaster's first on the market, or has moved by at least
   ``FORECAST_STEP`` since the last one recorded, or cost money, goes to
   the run's registry and as a ``forecast`` entry to the ledger; an
   unchanged one is not written again, so the ledger holds each
   forecaster's standing forecast over time without a copy per market per
   cycle (docs/paper_trading.md).
4. Size a position against the **real** touch of the book (best ask of the
   first outcome, or the complementary share at one minus the best bid),
   for no more than the cash the account has left after its open stakes,
   fill it at that price for at most the resting size at the touch, and
   record an ``order`` entry. Each forecaster keeps its own paper bankroll, compounded
   from its settled positions, so forecasters are compared on equal footing.
   One open position per forecaster per market.

:func:`settle` fetches each open position's market by condition id (the
CLOB path, which carries the ``winner`` flag), and for those the venue has
resolved writes a ``settlement`` entry with the profit and the Brier score
of the forecast behind the position. Pending or void markets stay open.

All state is derived by replaying the ledger, so the ledger is the only
store and a fresh process resumes exactly where the last one stopped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from vp.backtest.scoring import brier_one
from vp.backtest.sizing import FeeModel, Policy, fees_for
from vp.domains.base import Domain
from vp.domains.props import PROP_KINDS
from vp.forecast import Evidence, Forecaster
from vp.forecast.base import clip
from vp.forecast.registry import Registry
from vp.markets.polymarket import PolymarketSource
from vp.markets.schema import BinaryMarket
from vp.markets.snapshot import collect_snapshot
from vp.markets.store import read_markets
from vp.paper.ledger import ChainLedger, Entries

logger = logging.getLogger(__name__)

# The smallest change in a forecast worth recording again; well below the
# minimum edge a position needs, so no order is ever sized on an unrecorded
# forecast that differs from the recorded one by anything that matters.
FORECAST_STEP = 0.005

# The smallest stake worth placing, in dollars; below it an account with no
# cash left places nothing.
MIN_STAKE = 0.01


@dataclass
class Account:
    """One forecaster's paper account, replayed from the ledger."""

    bankroll: float
    open: dict[str, dict[str, Any]]  # market_id -> order data
    said: dict[str, float] = field(default_factory=dict)  # market_id -> p_hat


class MarketLookup(Protocol):
    """Fetches one market by condition id with its resolution, as settlement needs."""

    def market(self, identifier: str, *, depth: int = 0) -> BinaryMarket: ...


def replay(ledger: Entries, initial_cash: float) -> dict[str, Account]:
    """Bankrolls and open positions per forecaster from the ledger entries."""
    accounts: dict[str, Account] = {}
    for entry in ledger.entries():
        data = entry["data"]
        name = data.get("forecaster")
        if name is None:
            continue
        account = accounts.setdefault(name, Account(initial_cash, {}))
        if entry["kind"] == "forecast":
            account.said[data["market_id"]] = data["p_hat"]
        elif entry["kind"] == "order":
            account.open[data["market_id"]] = data
        elif entry["kind"] == "settlement":
            account.open.pop(data["market_id"], None)
            account.bankroll += data["pnl"]
    return accounts


def touch(market: BinaryMarket) -> tuple[float, float, float, float] | None:
    """(bid, ask, bid size, ask size) for the first outcome from the book or quote."""
    first = market.outcomes[0]
    if first.bids and first.asks:
        return (
            first.bids[0].price,
            first.asks[0].price,
            first.bids[0].size or 0.0,
            first.asks[0].size or 0.0,
        )
    if market.best_bid is not None and market.best_ask is not None:
        return market.best_bid, market.best_ask, 0.0, 0.0
    return None


def run_cycle(
    domain: Domain,
    forecasters: Sequence[Forecaster],
    source: PolymarketSource | None,
    root: Path,
    ledger: ChainLedger,
    *,
    depth: int = 5,
    max_markets: int | None = None,
    initial_cash: float = 1000.0,
    fees: FeeModel = FeeModel(),
    kelly_multiplier: float = 0.25,
    max_fraction: float = 0.05,
    min_edge: float = 0.0,
    now: datetime | None = None,
    snapshot: Path | None = None,
    policy: Policy | None = None,
    where: Callable[[BinaryMarket], bool] | None = None,
    window_hours: float | None = None,
) -> dict[str, int]:
    """Snapshot, forecast, and place simulated orders; returns counts.

    With ``snapshot`` the cycle trades against that existing capture
    instead of taking its own, which is how the platform runs many
    accounts off one capture of the venue rather than one each.

    A strategy (`vp.strategy`) passes its ``policy`` (rule and caps, in
    place of the three sizing numbers), its selector as ``where`` (without
    one, every parsed market but the props), and ``window_hours``: only
    markets whose scheduled end is at most that far away are forecast.
    """
    policy = policy or Policy(kelly_multiplier, max_fraction, min_edge)
    where = where or (lambda m: m.parsed.get("kind") not in PROP_KINDS)
    now = now or datetime.now(tz=timezone.utc)
    if snapshot is None:
        if source is None:
            raise ValueError("a cycle without a snapshot needs a source to take one")
        path, count = collect_snapshot(
            domain, source, root, depth=depth, max_markets=max_markets
        )
    else:
        path = snapshot
    captured = read_markets(path)
    if snapshot is not None:
        count = len(captured)
    markets = [
        m
        for m in captured
        if m.parsed.get("kind") and where(m) and _within(m, now, window_hours)
    ]
    evidence = Evidence(now, root)
    registry = Registry(root / "paper" / "forecasts.jsonl")
    accounts = replay(ledger, initial_cash)
    counts = {
        "snapshot": count,
        "parsed": len(markets),
        "forecasts": 0,
        "recorded": 0,
        "orders": 0,
    }
    ledger.append(
        "cycle",
        {
            "domain": domain.name,
            # Relative to the data root where possible, so the record names
            # the capture rather than a machine's directory layout.
            "snapshot": str(
                path.relative_to(root) if path.is_relative_to(root) else path
            ),
            "markets": count,
        },
    )
    for market in markets:
        quote = touch(market)
        for forecaster in forecasters:
            account = accounts.setdefault(forecaster.name, Account(initial_cash, {}))
            if market.market_id is None or market.market_id in account.open:
                continue
            forecast = forecaster.forecast(market, evidence)
            if forecast is None:
                continue
            counts["forecasts"] += 1
            said = account.said.get(market.market_id)
            if (
                said is None
                or abs(forecast.p_hat - said) >= FORECAST_STEP
                or forecast.cost_usd  # a paid forecast is always on the record
            ):
                registry.append(forecast)
                ledger.append(
                    "forecast",
                    {
                        "forecaster": forecaster.name,
                        "market_id": market.market_id,
                        "p_hat": forecast.p_hat,
                        "cost_usd": forecast.cost_usd,
                        "q": market.p_yes,
                    },
                )
                account.said[market.market_id] = forecast.p_hat
                counts["recorded"] += 1
            if quote is None or forecaster.name == "market":
                continue
            if not policy.admits(list(account.open.values()), market.event_id):
                continue
            bid, ask, bid_size, ask_size = quote
            market_fees, fee_source = fees_for(market, fees)
            position = policy.position(
                forecast.p_hat, ask=ask, bid=bid, fees=market_fees
            )
            if position is None:
                continue
            # An account spends only cash it has: its bankroll less what its
            # open positions have staked. Sizing on the bankroll alone let an
            # account stake 135 times its bankroll across a cycle's markets
            # (found 2026-09-23, docs/paper_trading.md).
            cash = account.bankroll - sum(o["stake"] for o in account.open.values())
            stake = policy.stake(position.fraction, account.bankroll, cash)
            if stake < MIN_STAKE:
                continue
            shares = stake / position.price
            resting = ask_size if position.side == "yes" else bid_size
            if resting > 0:
                shares = min(shares, resting)
                stake = shares * position.price
            quoted = ask if position.side == "yes" else 1.0 - bid
            order = {
                "forecaster": forecaster.name,
                "market_id": market.market_id,
                "condition_id": market.condition_id,
                "event_id": market.event_id,
                "question": market.question,
                "side": position.side,
                "price": position.price,
                "shares": shares,
                "stake": stake,
                "fee": shares * (position.price - quoted),
                "fee_rate": market_fees.rate,
                "fee_source": fee_source,
                "p_hat": forecast.p_hat,
                "q": market.p_yes,
                "bankroll_before": account.bankroll,
            }
            ledger.append("order", order)
            account.open[market.market_id] = order
            counts["orders"] += 1
    return counts


def _within(market: BinaryMarket, now: datetime, hours: float | None) -> bool:
    """Whether the market's scheduled end is in the next ``hours`` (always
    true without a window; false for a market with no end date)."""
    if hours is None:
        return True
    if not market.end_date:
        return False
    try:
        end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
    except ValueError:
        return False
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    left = (end - now).total_seconds() / 3600
    return 0 < left <= hours


def settle(
    source: MarketLookup, ledger: ChainLedger, *, initial_cash: float = 1000.0
) -> dict[str, int]:
    """Settle open positions whose markets the venue has resolved."""
    accounts = replay(ledger, initial_cash)
    counts = {"open": 0, "settled": 0, "pending": 0, "void": 0, "errors": 0}
    seen: dict[str, BinaryMarket | None] = {}
    for name, account in accounts.items():
        for market_id, order in list(account.open.items()):
            counts["open"] += 1
            condition = order.get("condition_id")
            if not condition:
                counts["errors"] += 1
                continue
            if condition not in seen:
                try:
                    seen[condition] = source.market(condition)
                except Exception as exc:  # noqa: BLE001 - keep settling the rest
                    logger.warning("settle: fetch failed for %s: %s", condition, exc)
                    seen[condition] = None
            market = seen[condition]
            if market is None:
                counts["errors"] += 1
                continue
            if market.resolution_state != "resolved":
                counts["pending"] += 1
                continue
            label = market.resolved_outcome
            if label is None:
                counts["void"] += 1
                continue
            won = label == (1 if order["side"] == "yes" else 0)
            pnl = order["shares"] - order["stake"] if won else -order["stake"]
            q = order.get("q")
            ledger.append(
                "settlement",
                {
                    "forecaster": name,
                    "market_id": market_id,
                    "label": label,
                    "pnl": pnl,
                    "brier": brier_one(clip(order["p_hat"]), label),
                    "brier_market": brier_one(clip(q), label)
                    if q is not None
                    else None,
                    "bankroll_after": account.bankroll + pnl,
                },
            )
            account.bankroll += pnl
            account.open.pop(market_id)
            counts["settled"] += 1
    return counts
