"""The binary-contract record and its Parquet round trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from vp.markets import store
from vp.markets.schema import market_from_record

STAMP = "2026-09-12T00:00:00Z"


def record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "market_id": "1",
        "condition_id": "0xabc",
        "slug": "arsenal-chelsea",
        "question": "Will Arsenal win?",
        "status": "resolved",
        "trading_closed": True,
        "resolution": {"state": "resolved", "winning_outcome": "No"},
        "end_date": "2026-05-24",
        "closed_time": None,
        "outcomes": [
            {
                "outcome": "Yes",
                "clob_token_id": "7",
                "implied_probability": 0.0,
                "book": {
                    "bids": [],
                    "asks": [{"implied_probability": 0.02, "size": 10.0}],
                },
            },
            {"outcome": "No", "clob_token_id": "8", "implied_probability": 1.0},
        ],
        "best_bid": 0.0,
        "best_ask": 0.02,
        "spread": 0.02,
        "last_trade_price": 0.01,
        "volume_usd": 100.0,
        "liquidity_usd": 5.0,
    }
    base.update(overrides)
    return base


def test_label_follows_first_outcome() -> None:
    market = market_from_record(
        record(),
        event_id="e",
        event_title="Arsenal vs Chelsea",
        tags=("EPL",),
        fetched_at=STAMP,
    )
    assert market.resolved_outcome == 0
    assert market.p_yes == 0.0
    assert market.outcomes[0].asks[0].price == 0.02
    yes = record(resolution={"state": "resolved", "winning_outcome": "Yes"})
    assert (
        market_from_record(
            yes, event_id=None, event_title=None, tags=(), fetched_at=STAMP
        ).resolved_outcome
        == 1
    )
    void = record(resolution={"state": "resolved", "winning_outcome": None})
    assert (
        market_from_record(
            void, event_id=None, event_title=None, tags=(), fetched_at=STAMP
        ).resolved_outcome
        is None
    )
    pending = record(resolution={"state": "pending", "implied_winning_outcome": "No"})
    assert (
        market_from_record(
            pending, event_id=None, event_title=None, tags=(), fetched_at=STAMP
        ).resolved_outcome
        is None
    )


def test_non_binary_is_rejected() -> None:
    three = record(outcomes=[{"outcome": "A"}, {"outcome": "B"}, {"outcome": "C"}])
    with pytest.raises(ValueError):
        market_from_record(
            three, event_id=None, event_title=None, tags=(), fetched_at=STAMP
        )
    with pytest.raises(ValueError):
        market_from_record(
            record(question=""),
            event_id=None,
            event_title=None,
            tags=(),
            fetched_at=STAMP,
        )


def test_parquet_round_trip(tmp_path: Path) -> None:
    market = market_from_record(
        record(),
        event_id="e",
        event_title="Arsenal vs Chelsea",
        tags=("EPL", "Soccer"),
        fetched_at=STAMP,
    )
    from dataclasses import replace

    market = replace(
        market,
        domain="epl",
        parsed={"kind": "match", "side": "Arsenal"},
        fee_rate=0.05,
    )
    path = tmp_path / "markets.parquet"
    store.write_markets(path, [market])
    assert store.read_markets(path) == [market]
    # An empty file still carries the schema.
    store.write_markets(tmp_path / "empty.parquet", [])
    assert store.read_markets(tmp_path / "empty.parquet") == []


def test_history_round_trip(tmp_path: Path) -> None:
    points = [
        {"timestamp": "2026-01-01T00:00:00Z", "implied_probability": 0.4},
        {"timestamp": "2026-01-02T00:00:00Z", "implied_probability": 0.6},
    ]
    path = tmp_path / "h.parquet"
    store.write_history(
        path, market_id="1", clob_token_id="7", outcome="Yes", points=points
    )
    rows = store.read_history(path)
    assert [r["implied_probability"] for r in rows] == [0.4, 0.6]
    assert rows[0]["market_id"] == "1" and rows[0]["outcome"] == "Yes"


def test_files_without_fee_columns_read_as_not_stated(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    market = market_from_record(
        record(), event_id="e", event_title="t", tags=(), fetched_at=STAMP
    )
    old = pa.schema([f for f in store.MARKET_SCHEMA if not f.name.startswith("fee_")])
    row = {k: v for k, v in store.market_to_row(market).items() if k in old.names}
    pq.write_table(pa.Table.from_pylist([row], schema=old), tmp_path / "old.parquet")
    (read,) = store.read_markets(tmp_path / "old.parquet")
    assert read.fee_rate is None and read.fee_exponent == 1.0
