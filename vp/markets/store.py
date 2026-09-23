"""Parquet persistence for market records and price histories.

Two tables. ``markets`` holds one row per :class:`BinaryMarket` observation,
with the two outcomes flattened into numbered columns and each order book as a
list of ``{price, size}`` structs, so a file is readable by any Parquet tool
without this package. ``histories`` holds one row per price point of one
outcome token, with the bar width the series was served at. Both schemas are
explicit rather than inferred so that a file written from an empty list still
carries the columns.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from vp.markets.schema import BinaryMarket, BookLevel, Outcome

_BOOK = pa.list_(pa.struct([("price", pa.float64()), ("size", pa.float64())]))

MARKET_SCHEMA = pa.schema(
    [
        ("market_id", pa.string()),
        ("condition_id", pa.string()),
        ("slug", pa.string()),
        ("question", pa.string()),
        ("event_id", pa.string()),
        ("event_title", pa.string()),
        ("domain", pa.string()),
        ("status", pa.string()),
        ("trading_closed", pa.bool_()),
        ("resolution_state", pa.string()),
        ("winning_outcome", pa.string()),
        ("resolved_outcome", pa.int8()),
        ("end_date", pa.string()),
        ("closed_time", pa.string()),
        ("outcome_0_name", pa.string()),
        ("outcome_0_token", pa.string()),
        ("outcome_0_price", pa.float64()),
        ("outcome_0_bids", _BOOK),
        ("outcome_0_asks", _BOOK),
        ("outcome_1_name", pa.string()),
        ("outcome_1_token", pa.string()),
        ("outcome_1_price", pa.float64()),
        ("outcome_1_bids", _BOOK),
        ("outcome_1_asks", _BOOK),
        ("best_bid", pa.float64()),
        ("best_ask", pa.float64()),
        ("spread", pa.float64()),
        ("last_trade_price", pa.float64()),
        ("volume_usd", pa.float64()),
        ("liquidity_usd", pa.float64()),
        ("tags", pa.list_(pa.string())),
        ("fetched_at", pa.string()),
        ("parsed", pa.map_(pa.string(), pa.string())),
        ("fee_rate", pa.float64()),
        ("fee_exponent", pa.float64()),
    ]
)

HISTORY_SCHEMA = pa.schema(
    [
        ("market_id", pa.string()),
        ("clob_token_id", pa.string()),
        ("outcome", pa.string()),
        ("timestamp", pa.string()),
        ("implied_probability", pa.float64()),
        ("bar_minutes", pa.int32()),
    ]
)


def _book(levels: tuple[BookLevel, ...]) -> list[dict[str, float | None]]:
    return [asdict(level) for level in levels]


def market_to_row(market: BinaryMarket) -> dict[str, Any]:
    """Flatten a record into one Parquet row."""
    first, second = market.outcomes
    return {
        "market_id": market.market_id,
        "condition_id": market.condition_id,
        "slug": market.slug,
        "question": market.question,
        "event_id": market.event_id,
        "event_title": market.event_title,
        "domain": market.domain,
        "status": market.status,
        "trading_closed": market.trading_closed,
        "resolution_state": market.resolution_state,
        "winning_outcome": market.winning_outcome,
        "resolved_outcome": market.resolved_outcome,
        "end_date": market.end_date,
        "closed_time": market.closed_time,
        "outcome_0_name": first.name,
        "outcome_0_token": first.clob_token_id,
        "outcome_0_price": first.implied_probability,
        "outcome_0_bids": _book(first.bids),
        "outcome_0_asks": _book(first.asks),
        "outcome_1_name": second.name,
        "outcome_1_token": second.clob_token_id,
        "outcome_1_price": second.implied_probability,
        "outcome_1_bids": _book(second.bids),
        "outcome_1_asks": _book(second.asks),
        "best_bid": market.best_bid,
        "best_ask": market.best_ask,
        "spread": market.spread,
        "last_trade_price": market.last_trade_price,
        "volume_usd": market.volume_usd,
        "liquidity_usd": market.liquidity_usd,
        "tags": list(market.tags),
        "fetched_at": market.fetched_at,
        "parsed": list(market.parsed.items()),
        "fee_rate": market.fee_rate,
        "fee_exponent": market.fee_exponent,
    }


def _outcome(row: dict[str, Any], index: int) -> Outcome:
    prefix = f"outcome_{index}_"
    return Outcome(
        name=row[prefix + "name"],
        clob_token_id=row[prefix + "token"],
        implied_probability=row[prefix + "price"],
        bids=tuple(BookLevel(**lvl) for lvl in row[prefix + "bids"] or ()),
        asks=tuple(BookLevel(**lvl) for lvl in row[prefix + "asks"] or ()),
    )


def market_from_row(row: dict[str, Any]) -> BinaryMarket:
    """Rebuild a record from one Parquet row."""
    return BinaryMarket(
        market_id=row["market_id"],
        condition_id=row["condition_id"],
        slug=row["slug"],
        question=row["question"],
        event_id=row["event_id"],
        event_title=row["event_title"],
        domain=row["domain"],
        status=row["status"],
        trading_closed=row["trading_closed"],
        resolution_state=row["resolution_state"],
        winning_outcome=row["winning_outcome"],
        resolved_outcome=row["resolved_outcome"],
        end_date=row["end_date"],
        closed_time=row["closed_time"],
        outcomes=(_outcome(row, 0), _outcome(row, 1)),
        best_bid=row["best_bid"],
        best_ask=row["best_ask"],
        spread=row["spread"],
        last_trade_price=row["last_trade_price"],
        volume_usd=row["volume_usd"],
        liquidity_usd=row["liquidity_usd"],
        tags=tuple(row["tags"] or ()),
        fetched_at=row["fetched_at"],
        parsed=dict(row["parsed"] or ()),
        # Files written before the fee columns existed read as "not stated".
        fee_rate=row.get("fee_rate"),
        fee_exponent=row.get("fee_exponent") or 1.0,
    )


def write_markets(path: Path, markets: list[BinaryMarket]) -> None:
    """Write records to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(
        [market_to_row(m) for m in markets], schema=MARKET_SCHEMA
    )
    pq.write_table(table, path)


def read_markets(path: Path) -> list[BinaryMarket]:
    """Read records written by :func:`write_markets`."""
    return [market_from_row(row) for row in pq.read_table(path).to_pylist()]


def write_history(
    path: Path,
    *,
    market_id: str | None,
    clob_token_id: str | None,
    outcome: str | None,
    points: list[dict[str, Any]],
    bar_minutes: int | None = None,
) -> None:
    """Write one outcome token's price series as returned by the client."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "market_id": market_id,
            "clob_token_id": clob_token_id,
            "outcome": outcome,
            "timestamp": point["timestamp"],
            "implied_probability": point["implied_probability"],
            "bar_minutes": bar_minutes,
        }
        for point in points
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=HISTORY_SCHEMA), path)


def read_history(path: Path) -> list[dict[str, Any]]:
    """Read a series written by :func:`write_history`."""
    return pq.read_table(path).to_pylist()
