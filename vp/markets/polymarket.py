"""Polymarket as a source of :class:`BinaryMarket` records.

Wraps the read-only client so that everything above this layer handles typed
records and domains rather than raw dictionaries. The client functions are
attributes of the source so tests can substitute fakes; nothing here touches
the network except through them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

from vp.domains.base import Domain
from vp.markets.schema import BinaryMarket, BookLevel, market_from_record, utc_now_iso
from vp.venues import polymarket as client

logger = logging.getLogger(__name__)


class PolymarketSource:
    """Typed access to Polymarket markets, with domain filtering.

    Args:
        iter_events: Pager over the catalogue by tag and trading state.
        search_events: Keyword search returning events with markets.
        fetch_market: Single-market fetch by id or condition id, with depth.
        fetch_book: Order-book fetch by token id.
        fetch_history: Price-history fetch for one outcome token.
        now: Clock for ``fetched_at`` stamps.
    """

    def __init__(
        self,
        *,
        iter_events: Callable[..., Iterator[dict[str, Any]]] = client.iter_events,
        search_events: Callable[..., dict[str, Any]] = client.search_events,
        fetch_market: Callable[..., dict[str, Any]] = client.fetch_market,
        fetch_book: Callable[..., dict[str, Any]] = client.fetch_book,
        fetch_history: Callable[..., dict[str, Any]] = client.fetch_history,
        now: Callable[[], str] = utc_now_iso,
    ) -> None:
        self._iter_events = iter_events
        self._search_events = search_events
        self._fetch_market = fetch_market
        self._fetch_book = fetch_book
        self._fetch_history = fetch_history
        self._now = now

    def markets_from_event(
        self, event: dict[str, Any], *, domain: Domain | None = None
    ) -> list[BinaryMarket]:
        """Convert an event's markets, keeping those that belong to ``domain``.

        Markets that are not binary (not exactly two outcomes) are skipped with
        a debug log; they are not errors, just not contracts of the kind
        forecast here.
        """
        fetched_at = self._now()
        tags = tuple(event.get("tags") or ())
        event_id = event.get("event_id")
        title = event.get("title")
        out: list[BinaryMarket] = []
        for record in event.get("markets") or []:
            try:
                market = market_from_record(
                    record,
                    event_id=event_id,
                    event_title=title,
                    tags=tags,
                    fetched_at=fetched_at,
                )
            except ValueError as exc:
                logger.debug("skipping market %s: %s", record.get("market_id"), exc)
                continue
            if domain is not None:
                if not domain.matches(market.question, title, tags):
                    continue
                parsed = domain.parse(market.question, title) or {}
                market = replace(market, domain=domain.name, parsed=parsed)
            out.append(market)
        return out

    def discover(
        self, domain: Domain, *, closed: bool | None, search_limit: int = 25
    ) -> Iterator[BinaryMarket]:
        """Yield the domain's markets, de-duplicated by market id.

        Two routes are combined: paging the catalogue by each of the domain's
        tag ids, which is exhaustive for a tag, and a keyword search per
        domain keyword, which catches untagged markets but is relevance-ranked
        and capped by the venue. ``closed`` selects trading state; ``None``
        takes both.
        """
        seen: set[str] = set()

        def emit(markets: list[BinaryMarket]) -> Iterator[BinaryMarket]:
            for market in markets:
                key = market.market_id or market.condition_id or market.question
                if key in seen:
                    continue
                seen.add(key)
                yield market

        for tag_id in domain.tag_ids:
            for event in self._iter_events(tag_id=tag_id, closed=closed):
                yield from emit(self.markets_from_event(event, domain=domain))

        statuses = (
            ["open", "closed"] if closed is None else ["closed" if closed else "open"]
        )
        for keyword in domain.keywords:
            for status in statuses:
                result = self._search_events(
                    keyword, limit=search_limit, status=status, with_markets=True
                )
                for event in result.get("events") or []:
                    yield from emit(self.markets_from_event(event, domain=domain))

    def with_books(self, market: BinaryMarket, *, depth: int) -> BinaryMarket:
        """Return a copy of ``market`` with ``depth`` book levels per outcome."""
        outcomes = []
        for outcome in market.outcomes:
            if outcome.clob_token_id is None:
                outcomes.append(outcome)
                continue
            book = self._fetch_book(outcome.clob_token_id, depth=depth)
            outcomes.append(
                replace(
                    outcome,
                    bids=tuple(_levels(book.get("bids"))),
                    asks=tuple(_levels(book.get("asks"))),
                )
            )
        return replace(
            market, outcomes=(outcomes[0], outcomes[1]), fetched_at=self._now()
        )

    def market(self, identifier: str, *, depth: int = 0) -> BinaryMarket:
        """Fetch one market by Gamma id or condition id, without event context."""
        record = self._fetch_market(identifier, depth=depth)
        return market_from_record(
            record, event_id=None, event_title=None, tags=(), fetched_at=self._now()
        )

    def history(
        self, market: BinaryMarket, *, outcome_index: int = 0
    ) -> dict[str, Any]:
        """Full price history of one of the market's outcome tokens."""
        outcome = market.outcomes[outcome_index]
        if outcome.clob_token_id is None:
            raise ValueError("outcome has no CLOB token id")
        return self._fetch_history(outcome.clob_token_id, interval="max")


def _levels(raw: Any) -> list[BookLevel]:
    if not isinstance(raw, list):
        return []
    return [
        BookLevel(price=float(lvl["implied_probability"]), size=lvl.get("size"))
        for lvl in raw
        if isinstance(lvl, dict) and "implied_probability" in lvl
    ]
