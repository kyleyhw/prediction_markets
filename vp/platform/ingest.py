"""The market-data service: one subscription to the venue, for everyone.

`vp ingest` is the only process that watches the venue continuously. Users
never poll it; their paper cycles, views and settlements read what this
service records:

* **Discovery.** Each domain's open markets, found by the client's keyset
  pagination, are written to `tracked_markets` every few minutes.
* **Books.** One WebSocket per few hundred tokens on the CLOB market
  channel with the custom features on (`best_bid_ask`, `new_market`,
  `market_resolved`), a `PING` every ten seconds, dynamic subscription as
  discovery finds new tokens, and reconnection with backoff. Books live in
  memory.
* **Quotes.** Once a minute, every token's best bid and ask go to `quotes`,
  one row per token per minute; a market any paper account holds is also
  quoted on every change of its top of book.
* **Snapshots.** On a schedule, each domain's markets with their current
  books are written in the engine's snapshot format to the object store, so
  every file downstream is what `vp snapshot` has always written, and a
  `NOTIFY vp_data` tells listeners there is a new one.
* **Resolutions.** A `market_resolved` event is recorded in `resolutions`
  as it arrives; the hourly `reconcile` job asks the Data API v2 about
  every market past its end date that is still unresolved, so a missed
  event costs at most an hour. The label itself is still set only by
  settlement from the venue's record: closed is not resolved.

Its health is measured by two objectives (docs/platform.md): the newest
quote is under 60 seconds old at the 99th percentile, and a resolution
becomes a label within 15 minutes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.domains import DOMAINS
from vp.markets.polymarket import PolymarketSource
from vp.markets.schema import BinaryMarket, BookLevel, utc_now_iso
from vp.markets.store import market_to_row, write_markets
from vp.platform.jobs import JobContext
from vp.platform.observe import RESOLUTION_DELAY
from vp.platform.storage import SHARED, ObjectStore
from vp.venues import polymarket as client

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
TOKENS_PER_SOCKET = 400
PING_SECONDS = 10.0


# ------------------------------------------------------------------ books


@dataclass
class Book:
    """One token's order book as the channel has described it."""

    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    best_bid: float | None = None
    best_ask: float | None = None
    updated: float = 0.0  # epoch seconds of the last change

    def top(self) -> tuple[float | None, float | None]:
        bid = max(self.bids) if self.bids else self.best_bid
        ask = min(self.asks) if self.asks else self.best_ask
        return bid, ask

    def levels(self, depth: int) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
        """The `depth` levels nearest the touch on each side, best first."""
        bids = sorted(self.bids.items(), key=lambda kv: -kv[0])[:depth]
        asks = sorted(self.asks.items(), key=lambda kv: kv[0])[:depth]
        return (
            tuple(BookLevel(price=p, size=s) for p, s in bids),
            tuple(BookLevel(price=p, size=s) for p, s in asks),
        )


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


@dataclass
class MarketState:
    """Every tracked market and every token's book, in memory."""

    markets: dict[str, BinaryMarket] = field(default_factory=dict)
    token_market: dict[str, str] = field(default_factory=dict)
    books: dict[str, Book] = field(default_factory=dict)
    resolved: list[dict[str, Any]] = field(default_factory=list)
    new_markets: int = 0

    def track(self, markets: Iterable[BinaryMarket]) -> list[str]:
        """Add or refresh markets; returns tokens not seen before."""
        fresh: list[str] = []
        for m in markets:
            if m.market_id is None:
                continue
            self.markets[m.market_id] = m
            for outcome in m.outcomes:
                token = outcome.clob_token_id
                if token and token not in self.token_market:
                    self.token_market[token] = m.market_id
                    fresh.append(token)
        return fresh

    def apply(self, event: dict[str, Any], now: float | None = None) -> set[str]:
        """Apply one channel event; returns the tokens whose top of book moved."""
        now = now or time.time()
        kind = event.get("event_type")
        moved: set[str] = set()
        if kind == "book":
            token = str(event.get("asset_id"))
            book = self.books.setdefault(token, Book())
            before = book.top()
            book.bids = {
                p: s
                for lvl in event.get("bids") or []
                if (p := _num(lvl.get("price"))) is not None
                and (s := _num(lvl.get("size")))
            }
            book.asks = {
                p: s
                for lvl in event.get("asks") or []
                if (p := _num(lvl.get("price"))) is not None
                and (s := _num(lvl.get("size")))
            }
            book.updated = now
            if book.top() != before:
                moved.add(token)
        elif kind == "price_change":
            for change in event.get("price_changes") or []:
                token = str(change.get("asset_id"))
                book = self.books.setdefault(token, Book())
                before = book.top()
                price, size = _num(change.get("price")), _num(change.get("size"))
                side = book.bids if change.get("side") == "BUY" else book.asks
                if price is not None:
                    if size:
                        side[price] = size
                    else:
                        side.pop(price, None)
                book.best_bid = _num(change.get("best_bid")) or book.best_bid
                book.best_ask = _num(change.get("best_ask")) or book.best_ask
                book.updated = now
                if book.top() != before:
                    moved.add(token)
        elif kind == "best_bid_ask":
            token = str(event.get("asset_id"))
            book = self.books.setdefault(token, Book())
            before = book.top()
            book.best_bid = _num(event.get("best_bid"))
            book.best_ask = _num(event.get("best_ask"))
            book.updated = now
            if book.top() != before:
                moved.add(token)
        elif kind == "market_resolved":
            self.resolved.append(event)
        elif kind == "new_market":
            self.new_markets += 1
        return moved

    def snapshot(self, domain: str, depth: int = 5) -> list[BinaryMarket]:
        """The domain's markets with their current books, as a snapshot holds them."""
        stamp = utc_now_iso()
        out = []
        for m in self.markets.values():
            if m.domain != domain:
                continue
            outcomes = []
            for o in m.outcomes:
                book = self.books.get(o.clob_token_id or "")
                if book is None:
                    outcomes.append(o)
                    continue
                bids, asks = book.levels(depth)
                outcomes.append(replace(o, bids=bids, asks=asks))
            first = self.books.get(m.outcomes[0].clob_token_id or "")
            bid, ask = first.top() if first else (m.best_bid, m.best_ask)
            out.append(
                replace(
                    m,
                    outcomes=(outcomes[0], outcomes[1]),
                    best_bid=bid,
                    best_ask=ask,
                    fetched_at=stamp,
                )
            )
        return out

    def ages(self, now: float | None = None) -> list[float]:
        """Seconds since each subscribed token's book last changed or was sent."""
        now = now or time.time()
        return [now - b.updated for b in self.books.values() if b.updated]


# ------------------------------------------------------------- the service


def _winner_index(event: dict[str, Any], market: BinaryMarket | None) -> int | None:
    winner = event.get("winning_asset_id")
    if market is None or winner is None:
        return None
    tokens = [o.clob_token_id for o in market.outcomes]
    return tokens.index(str(winner)) if str(winner) in tokens else None


class Ingest:
    """The market-data service's loops, around one `MarketState`."""

    def __init__(
        self,
        pool: ConnectionPool,
        store: ObjectStore,
        domains: Iterable[str],
        *,
        source: PolymarketSource | None = None,
        connect: Callable[..., Any] | None = None,
        discover_seconds: float = 600.0,
        snapshot_seconds: float = 900.0,
        depth: int = 5,
        metrics: Any = None,
    ) -> None:
        self.pool = pool
        self.store = store
        self.domains = [d for d in domains if d in DOMAINS]
        self.source = source or PolymarketSource()
        self.connect = connect
        self.discover_seconds = discover_seconds
        self.snapshot_seconds = snapshot_seconds
        self.depth = depth
        self.metrics = metrics
        self.state = MarketState()
        self.held: set[str] = set()
        self.reconnects = 0
        self.messages = 0
        self._sockets: list[tuple[asyncio.Queue[list[str]], set[str]]] = []

    # -- discovery and the registry --

    def discover(self) -> list[str]:
        """Find the domains' open markets and record them; returns new tokens."""
        found: list[BinaryMarket] = []
        for name in self.domains:
            found.extend(self.source.discover(DOMAINS[name], closed=False))
        fresh = self.state.track(found)
        # A market that is no longer listed as open leaves the snapshots; its
        # token stays subscribed until the socket reconnects, which is harmless.
        self.state.markets = {m.market_id: m for m in found if m.market_id}
        started = datetime.now(tz=UTC)
        with self.pool.connection() as conn, conn.transaction():
            for m in found:
                conn.execute(
                    "insert into tracked_markets (market_id, condition_id, domain, "
                    "question, event_title, tokens, end_date, record) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "on conflict (market_id) do update set last_seen = now(), "
                    "record = excluded.record, end_date = excluded.end_date, "
                    "closed = false",
                    (
                        m.market_id,
                        m.condition_id,
                        m.domain,
                        m.question,
                        m.event_title,
                        [o.clob_token_id for o in m.outcomes if o.clob_token_id],
                        m.end_date,
                        Jsonb(json.loads(json.dumps(market_to_row(m), default=str))),
                    ),
                )
            conn.execute(
                "update tracked_markets set closed = true "
                "where domain = any(%s) and last_seen < %s and not closed",
                (self.domains, started),
            )
        return fresh

    def refresh_held(self) -> None:
        with self.pool.connection() as conn:
            rows = conn.execute("select market_id from vp_held_markets()").fetchall()
        self.held = {r[0] for r in rows if r[0]}

    # -- quotes and snapshots --

    def flush_quotes(self, moved: Iterable[str] | None = None) -> int:
        """Write tokens' tops: all of them to this minute's row, or `moved` now."""
        now = datetime.now(tz=UTC)
        minute = now.replace(second=0, microsecond=0) if moved is None else now
        tokens = list(self.state.books) if moved is None else list(moved)
        rows = []
        for token in tokens:
            book = self.state.books.get(token)
            market = self.state.token_market.get(token)
            if book is None or market is None:
                continue
            bid, ask = book.top()
            bid_size = book.bids.get(bid) if bid is not None else None
            ask_size = book.asks.get(ask) if ask is not None else None
            changed = datetime.fromtimestamp(book.updated or time.time(), tz=UTC)
            rows.append((token, market, minute, bid, ask, bid_size, ask_size, changed))
        if not rows:
            return 0
        with self.pool.connection() as conn, conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into quotes (token_id, market_id, minute, bid, ask, "
                    "bid_size, ask_size, changed_at) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "on conflict (token_id, minute) do update set bid = excluded.bid, "
                    "ask = excluded.ask, bid_size = excluded.bid_size, "
                    "ask_size = excluded.ask_size, changed_at = excluded.changed_at",
                    rows,
                )
        return len(rows)

    def write_snapshot(self, domain: str) -> str | None:
        """Write the domain's snapshot to the store; returns its key."""
        markets = self.state.snapshot(domain, self.depth)
        if not markets:
            return None
        stamp = utc_now_iso().replace("-", "").replace(":", "")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{stamp}.parquet"
            write_markets(path, markets)
            key = f"{SHARED}/snapshots/{domain}/{stamp}.parquet"
            self.store.put_file(key, path)
        with self.pool.connection() as conn:
            conn.execute("select pg_notify('vp_data', %s)", (f"snapshot:{domain}",))
        return key

    def record_resolutions(self) -> int:
        """Write any `market_resolved` events received since the last call."""
        events, self.state.resolved = self.state.resolved, []
        with self.pool.connection() as conn, conn.transaction():
            for e in events:
                condition = e.get("market") or e.get("condition_id")
                if not condition:
                    continue
                market_id = next(
                    (
                        m.market_id
                        for m in self.state.markets.values()
                        if m.condition_id == condition
                    ),
                    None,
                )
                market = self.state.markets.get(market_id or "")
                conn.execute(
                    "insert into resolutions (condition_id, market_id, status, "
                    "winner_index, source, payouts) "
                    "values (%s, %s, 'resolved', %s, 'ws', %s) "
                    "on conflict (condition_id) do update set status = 'resolved', "
                    "winner_index = excluded.winner_index, observed_at = now()",
                    (condition, market_id, _winner_index(e, market), Jsonb(e)),
                )
                conn.execute(
                    "update tracked_markets set closed = true where condition_id = %s",
                    (condition,),
                )
        return len(events)

    # -- the socket --

    async def _socket(self, tokens: set[str], extra: asyncio.Queue[list[str]]) -> None:
        import websockets

        connect = self.connect or websockets.connect
        backoff = 1.0
        while True:
            try:
                async with connect(WS_URL, proxy=True, open_timeout=20) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "assets_ids": sorted(tokens),
                                "type": "market",
                                "custom_feature_enabled": True,
                            }
                        )
                    )
                    backoff = 1.0
                    pinger = asyncio.create_task(self._ping(ws))
                    adder = asyncio.create_task(self._subscribe_more(ws, tokens, extra))
                    try:
                        async for raw in ws:
                            if raw == "PONG":
                                continue
                            self._handle(raw)
                    finally:
                        pinger.cancel()
                        adder.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect and carry on
                logger.warning("market channel dropped (%s); reconnecting", exc)
            self.reconnects += 1
            if self.metrics:
                self.metrics.reconnect()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _ping(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(PING_SECONDS)
            await ws.send("PING")

    async def _subscribe_more(
        self, ws: Any, tokens: set[str], extra: asyncio.Queue[list[str]]
    ) -> None:
        while True:
            more = await extra.get()
            tokens.update(more)
            await ws.send(json.dumps({"assets_ids": more, "operation": "subscribe"}))

    def _handle(self, raw: str | bytes) -> None:
        try:
            data = json.loads(raw)
        except ValueError:
            return
        moved: set[str] = set()
        for event in data if isinstance(data, list) else [data]:
            if isinstance(event, dict):
                self.messages += 1
                moved |= self.state.apply(event)
        held = {t for t in moved if self.state.token_market.get(t) in self.held}
        if held:
            with contextlib.suppress(Exception):
                self.flush_quotes(held)

    def assign(self, tokens: list[str]) -> list[tuple[set[str], list[str]]]:
        """Spread new tokens over the sockets, opening more as they fill."""
        plan: list[tuple[set[str], list[str]]] = []
        for queue_tokens in self._sockets:
            if not tokens:
                break
            _, current = queue_tokens
            room = TOKENS_PER_SOCKET - len(current)
            if room > 0:
                take, tokens = tokens[:room], tokens[room:]
                plan.append((current, take))
        while tokens:
            take, tokens = tokens[:TOKENS_PER_SOCKET], tokens[TOKENS_PER_SOCKET:]
            plan.append((set(), take))
        return plan

    # -- the loops --

    async def run(self, stop: asyncio.Event) -> None:
        tasks: list[asyncio.Task[None]] = []

        async def every(seconds: float, fn: Callable[[], Any], name: str) -> None:
            while not stop.is_set():
                try:
                    await asyncio.to_thread(fn)
                except Exception:  # noqa: BLE001 - the loop outlives one failure
                    logger.exception("%s failed", name)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), seconds)

        async def discover_and_subscribe() -> None:
            while not stop.is_set():
                try:
                    fresh = await asyncio.to_thread(self.discover)
                    for current, take in self.assign(fresh):
                        if not current:
                            queue: asyncio.Queue[list[str]] = asyncio.Queue()
                            tokens = set(take)
                            self._sockets.append((queue, tokens))
                            tasks.append(
                                asyncio.create_task(self._socket(tokens, queue))
                            )
                        else:
                            queue = next(q for q, t in self._sockets if t is current)
                            queue.put_nowait(take)
                    logger.info(
                        "tracking %d markets, %d tokens on %d sockets",
                        len(self.state.markets),
                        len(self.state.token_market),
                        len(self._sockets),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("discovery failed")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self.discover_seconds)

        def snapshots() -> None:
            for domain in self.domains:
                self.write_snapshot(domain)

        tasks += [
            asyncio.create_task(discover_and_subscribe()),
            asyncio.create_task(every(60.0, self.flush_quotes, "quote flush")),
            asyncio.create_task(every(300.0, self.refresh_held, "held markets")),
            asyncio.create_task(every(30.0, self.record_resolutions, "resolutions")),
            asyncio.create_task(every(15.0, self._measure, "metrics")),
        ]
        # The first snapshot waits for books to arrive after subscribing.
        await asyncio.sleep(min(60.0, self.snapshot_seconds))
        tasks.append(
            asyncio.create_task(every(self.snapshot_seconds, snapshots, "snapshots"))
        )
        await stop.wait()
        for t in tasks:
            t.cancel()

    def _measure(self) -> None:
        if self.metrics:
            self.metrics.freshness(self.state.ages(), len(self.state.token_market))


# ----------------------------------------------------------- reconciliation


def reconcile(ctx: JobContext) -> dict[str, Any]:
    """The hourly sweep: resolutions for markets past their end date.

    Asks the Data API v2 about each tracked market whose end date has
    passed and that has no resolution recorded, at most `limit` a run, and
    records what it says. The delay between the venue's resolution time and
    ours is the resolution-freshness objective's measurement.
    """
    limit = int(ctx.job.payload.get("limit", 300))
    with ctx.pool.connection() as conn:
        due = conn.execute(
            "select t.condition_id, t.market_id from tracked_markets t "
            "left join resolutions r on r.condition_id = t.condition_id "
            "where t.condition_id is not null and t.end_date < now() "
            "and (r.condition_id is null or r.status <> 'resolved') "
            "order by t.end_date limit %s",
            (limit,),
        ).fetchall()
    found = 0
    delays: list[float] = []
    for i, (condition, market_id) in enumerate(due):
        if i % 20 == 0:
            ctx.progress(i / max(len(due), 1), f"{i} of {len(due)} markets")
        record = client.fetch_resolution(condition)
        if record is None:
            continue
        with ctx.pool.connection() as conn:
            conn.execute(
                "insert into resolutions (condition_id, market_id, status, payouts, "
                "winner_index, source, resolved_at) values (%s, %s, %s, %s, %s, "
                "'data-api-v2', %s) on conflict (condition_id) do update set "
                "status = excluded.status, payouts = excluded.payouts, "
                "winner_index = excluded.winner_index, "
                "resolved_at = excluded.resolved_at, "
                "observed_at = now()",
                (
                    condition,
                    market_id,
                    record["status"],
                    Jsonb(record["payouts"]),
                    record["winner_index"],
                    record["resolved_at"],
                ),
            )
            if record["status"] == "resolved":
                conn.execute(
                    "update tracked_markets set closed = true where condition_id = %s",
                    (condition,),
                )
        if record["status"] == "resolved":
            found += 1
            if record["resolved_at"]:
                resolved = datetime.fromisoformat(
                    record["resolved_at"].replace("Z", "+00:00")
                )
                delay = (datetime.now(tz=UTC) - resolved).total_seconds()
                delays.append(delay)
                RESOLUTION_DELAY.observe(delay)
    return {
        "checked": len(due),
        "resolved": found,
        "max_delay_seconds": max(delays) if delays else None,
    }
