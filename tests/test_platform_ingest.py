"""The market-data service: channel events into books, books into the
engine's snapshots and the quotes table, resolutions recorded, and the
socket loop against a fake channel."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from tests.conftest import needs_db
from tests.test_paper import make_source
from vp.domains import CS2
from vp.markets.store import read_markets
from vp.platform import ingest
from vp.platform.ingest import Ingest, MarketState
from vp.platform.storage import LocalStore


def cs2_markets():
    return list(make_source([]).discover(CS2, closed=False))


def test_channel_events_keep_the_book() -> None:
    state = MarketState()
    (market,) = cs2_markets()
    fresh = state.track([market])
    first = market.outcomes[0].clob_token_id
    assert first in fresh
    moved = state.apply(
        {
            "event_type": "book",
            "asset_id": first,
            # The channel lists bids worst first; the book sorts them.
            "bids": [{"price": "0.40", "size": "10"}, {"price": "0.48", "size": "5"}],
            "asks": [{"price": "0.55", "size": "3"}, {"price": "0.52", "size": "7"}],
        },
        now=100.0,
    )
    assert moved == {first}
    book = state.books[first]
    assert book.top() == (0.48, 0.52)
    bids, asks = book.levels(1)
    assert (bids[0].price, asks[0].price, asks[0].size) == (0.48, 0.52, 7.0)
    # A level emptied and a new best bid.
    state.apply(
        {
            "event_type": "price_change",
            "price_changes": [
                {"asset_id": first, "price": "0.48", "size": "0", "side": "BUY"},
                {"asset_id": first, "price": "0.50", "size": "4", "side": "BUY"},
            ],
        }
    )
    assert book.top() == (0.50, 0.52)
    # A change that does not touch the top moves nothing.
    assert not state.apply(
        {
            "event_type": "price_change",
            "price_changes": [
                {"asset_id": first, "price": "0.30", "size": "9", "side": "BUY"}
            ],
        }
    )
    state.apply({"event_type": "market_resolved", "market": market.condition_id})
    assert len(state.resolved) == 1


def test_the_snapshot_is_the_engine_s_format(tmp_path: Path) -> None:
    state = MarketState()
    (market,) = cs2_markets()
    state.track([market.__class__(**{**market.__dict__, "domain": "cs2"})])
    token = market.outcomes[0].clob_token_id
    state.apply(
        {
            "event_type": "book",
            "asset_id": token,
            "bids": [{"price": "0.47", "size": "2"}],
            "asks": [{"price": "0.53", "size": "8"}],
        }
    )
    (snap,) = state.snapshot("cs2", depth=5)
    assert snap.outcomes[0].asks[0].price == 0.53 and snap.best_bid == 0.47
    from vp.markets.store import write_markets

    write_markets(tmp_path / "s.parquet", [snap])
    (back,) = read_markets(tmp_path / "s.parquet")
    assert back.outcomes[0].bids[0].size == 2.0 and back.market_id == market.market_id


@needs_db
def test_the_service_records_markets_quotes_snapshots_and_resolutions(
    app_pool, pg_owner, tmp_path: Path
) -> None:
    with pg_owner.transaction():
        for table in ("quotes", "resolutions", "tracked_markets"):
            pg_owner.execute(f"delete from {table}")
    store = LocalStore(tmp_path / "store")
    service = Ingest(app_pool, store, ["cs2"], source=make_source([]))
    fresh = service.discover()
    assert len(fresh) == 2  # both outcome tokens of the one market
    (tracked,) = pg_owner.execute(
        "select market_id, domain from tracked_markets"
    ).fetchall()
    assert tracked == ("6", "cs2")
    token = fresh[0]
    service.state.apply(
        {
            "event_type": "book",
            "asset_id": token,
            "bids": [{"price": "0.47", "size": "2"}],
            "asks": [{"price": "0.53", "size": "8"}],
        }
    )
    assert service.flush_quotes() == 1
    assert service.flush_quotes() == 0  # a quiet book writes nothing more
    service.state.apply(
        {
            "event_type": "best_bid_ask",
            "asset_id": token,
            "best_bid": "0.48",
            "best_ask": "0.53",
        }
    )
    assert service.flush_quotes() == 1  # the same minute is updated, not duplicated
    (n,) = pg_owner.execute("select count(*) from quotes").fetchone()
    assert n == 1
    key = service.write_snapshot("cs2")
    assert key and key.startswith("shared/snapshots/cs2/")
    local = tmp_path / "snap.parquet"
    assert store.download(key, local)
    assert read_markets(local)[0].outcomes[0].asks[0].price == 0.53
    service.state.apply(
        {"event_type": "market_resolved", "market": "0x6", "winning_asset_id": token}
    )
    assert service.record_resolutions() == 1
    row = pg_owner.execute(
        "select status, winner_index, source from resolutions where condition_id = '0x6'"
    ).fetchone()
    assert row == ("resolved", 0, "ws")


@needs_db
def test_reconciliation_asks_about_markets_past_their_end(
    app_pool, pg_owner, monkeypatch, tmp_path: Path
) -> None:
    from vp.platform.jobs import Worker, enqueue_platform

    with pg_owner.transaction():
        pg_owner.execute("delete from resolutions")
        pg_owner.execute("delete from tracked_markets")
        pg_owner.execute("delete from jobs where workspace_id is null")
        pg_owner.execute(
            "insert into tracked_markets (market_id, condition_id, domain, question, "
            "tokens, end_date, record) values "
            "('9', '0x9', 'cs2', 'q', '{}', now() - interval '2 hours', '{}'), "
            "('10', '0x10', 'cs2', 'q', '{}', now() + interval '2 days', '{}')"
        )
    asked: list[str] = []

    def fake_resolution(condition: str):
        asked.append(condition)
        return {
            "condition_id": condition,
            "status": "resolved",
            "payouts": [0, 1000000],
            "winner_index": 1,
            "resolved_at": "2026-09-23T00:00:00Z",
        }

    monkeypatch.setattr(ingest.client, "fetch_resolution", fake_resolution)
    job = enqueue_platform(app_pool, "reconcile", idempotency_key="test-reconcile")
    Worker(app_pool, {"reconcile": ingest.reconcile}, ("reconcile",)).run_once()
    assert asked == ["0x9"]  # only the market past its end date
    (result,) = pg_owner.execute(
        "select result from jobs where id = %s", (job,)
    ).fetchone()
    assert result["resolved"] == 1
    assert pg_owner.execute(
        "select winner_index, source from resolutions where condition_id = '0x9'"
    ).fetchone() == (1, "data-api-v2")


class FakeSocket:
    """A market channel that sends a book on subscription, then waits."""

    def __init__(self, sent: list) -> None:
        self.sent = sent
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, message: str) -> None:
        self.sent.append(message)
        data = json.loads(message) if message != "PING" else None
        if data and data.get("type") == "market":
            for token in data["assets_ids"]:
                await self._queue.put(
                    json.dumps(
                        [
                            {
                                "event_type": "book",
                                "asset_id": token,
                                "bids": [{"price": "0.4", "size": "1"}],
                                "asks": [{"price": "0.6", "size": "1"}],
                            }
                        ]
                    )
                )

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        return await self._queue.get()


def test_the_socket_subscribes_with_the_custom_features_and_fills_books() -> None:
    sent: list = []
    service = Ingest(None, None, ["cs2"], connect=lambda *a, **k: FakeSocket(sent))  # ty: ignore[invalid-argument-type]
    tokens = {"a1", "a2"}
    for t in tokens:
        service.state.token_market[t] = "m"

    async def go() -> None:
        task = asyncio.create_task(service._socket(set(tokens), asyncio.Queue()))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if len(service.state.books) == 2:
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    first = json.loads(sent[0])
    assert first["custom_feature_enabled"] is True and sorted(first["assets_ids"]) == [
        "a1",
        "a2",
    ]
    assert {t: b.top() for t, b in service.state.books.items()} == {
        "a1": (0.4, 0.6),
        "a2": (0.4, 0.6),
    }


def test_new_tokens_fill_sockets_before_opening_more() -> None:
    service = Ingest(None, None, [])  # ty: ignore[invalid-argument-type]
    service._sockets = [
        (asyncio.Queue(), {f"t{i}" for i in range(ingest.TOKENS_PER_SOCKET - 2)})
    ]
    plan = service.assign([f"n{i}" for i in range(5)])
    assert [len(take) for _, take in plan] == [2, 3]
    assert plan[0][0] is service._sockets[0][1] and plan[1][0] == set()


def test_the_venue_s_event_stamp_gives_the_ingestion_lag() -> None:
    class Seen:
        lags: list[float] = []

        def lag(self, seconds: float) -> None:
            self.lags.append(seconds)

    seen = Seen()
    service = Ingest(None, None, [], metrics=seen)  # ty: ignore[invalid-argument-type]
    stamp = int((time.time() - 0.5) * 1000)
    old = int((time.time() - 86_400) * 1000)
    service._handle(
        json.dumps(
            [
                {
                    "event_type": "best_bid_ask",
                    "asset_id": "a",
                    "timestamp": str(stamp),
                },
                # A picture of a book stamped with its last change says
                # nothing about the lag.
                {"event_type": "book", "asset_id": "b", "timestamp": str(old)},
            ]
        )
    )
    assert len(seen.lags) == 1 and 0.4 < seen.lags[0] < 5


def test_a_book_is_as_stale_as_its_socket_is_silent() -> None:
    service = Ingest(None, None, [])  # ty: ignore[invalid-argument-type]
    live, silent = {"a", "b", "c"}, {"d"}
    service._sockets = [(asyncio.Queue(), live), (asyncio.Queue(), silent)]
    now = time.time()
    service._started = now - 100
    service._heard[id(live)] = now - 2
    assert sorted(service.staleness(now)) == pytest.approx([2, 2, 2, 100])
