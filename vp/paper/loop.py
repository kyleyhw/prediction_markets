"""The forward paper-trading loop and its settlement pass.

One cycle of :func:`run_cycle`:

1. Snapshot the domain's open markets with book depth (the same collector
   the data layer uses, so the snapshot files accumulate as before).
2. Build the evidence view at *now*: the resolved sets give results and
   observations up to the present, and nothing after it exists yet, so the
   forward loop cannot look ahead by construction. Its scores are therefore
   the honest counterpart of the backtest's; Phase 10's leakage check
   compares the two.
3. Ask each forecaster for every parsed market it accepts; append the
   forecast to the run's registry and a ``forecast`` entry to the ledger.
4. Size a position against the **real** touch of the book (best ask of the
   first outcome, or the complementary share at one minus the best bid), fill
   it at that price for at most the resting size at the touch, and record an
   ``order`` entry. Each forecaster keeps its own paper bankroll, compounded
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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vp.backtest.scoring import brier_one
from vp.backtest.sizing import FeeModel, fees_for, size
from vp.domains.base import Domain
from vp.forecast import Evidence, Forecaster
from vp.forecast.base import clip
from vp.forecast.registry import Registry
from vp.markets.polymarket import PolymarketSource
from vp.markets.schema import BinaryMarket
from vp.markets.snapshot import collect_snapshot
from vp.markets.store import read_markets
from vp.paper.ledger import Ledger

logger = logging.getLogger(__name__)


@dataclass
class Account:
    """One forecaster's paper account, replayed from the ledger."""

    bankroll: float
    open: dict[str, dict[str, Any]]  # market_id -> order data


def replay(ledger: Ledger, initial_cash: float) -> dict[str, Account]:
    """Bankrolls and open positions per forecaster from the ledger entries."""
    accounts: dict[str, Account] = {}
    for entry in ledger.entries():
        data = entry["data"]
        name = data.get("forecaster")
        if name is None:
            continue
        account = accounts.setdefault(name, Account(initial_cash, {}))
        if entry["kind"] == "order":
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
    source: PolymarketSource,
    root: Path,
    ledger: Ledger,
    *,
    depth: int = 5,
    max_markets: int | None = None,
    initial_cash: float = 1000.0,
    fees: FeeModel = FeeModel(),
    kelly_multiplier: float = 0.25,
    max_fraction: float = 0.05,
    min_edge: float = 0.0,
    now: datetime | None = None,
) -> dict[str, int]:
    """Snapshot, forecast, and place simulated orders; returns counts."""
    now = now or datetime.now(tz=timezone.utc)
    path, count = collect_snapshot(
        domain, source, root, depth=depth, max_markets=max_markets
    )
    markets = [m for m in read_markets(path) if m.parsed.get("kind")]
    evidence = Evidence(now, root)
    registry = Registry(root / "paper" / "forecasts.jsonl")
    accounts = replay(ledger, initial_cash)
    counts = {"snapshot": count, "parsed": len(markets), "forecasts": 0, "orders": 0}
    ledger.append(
        "cycle", {"domain": domain.name, "snapshot": str(path), "markets": count}
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
            registry.append(forecast)
            counts["forecasts"] += 1
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
            if quote is None or forecaster.name == "market":
                continue
            bid, ask, bid_size, ask_size = quote
            market_fees, fee_source = fees_for(market, fees)
            position = size(
                forecast.p_hat,
                ask=ask,
                bid=bid,
                fees=market_fees,
                kelly_multiplier=kelly_multiplier,
                max_fraction=max_fraction,
                min_edge=min_edge,
            )
            if position is None:
                continue
            stake = position.fraction * account.bankroll
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


def settle(
    source: PolymarketSource, ledger: Ledger, *, initial_cash: float = 1000.0
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
