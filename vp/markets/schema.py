"""The binary-contract record.

Every Polymarket market is a pair of outcome tokens; the first token pays 1 if
its outcome occurs and the second pays 1 otherwise, so the record fixes the
*first* outcome as the event $A$ whose probability is forecast. For a
"Yes"/"No" market that is "Yes"; for a match market with outcomes
``["Spirit", "Falcons"]`` it is the first-named team. Everything downstream, the
forecast $\\hat p$, the market price $q$, and the resolved label $y$, refers to
that first outcome.

The record is frozen so a snapshot cannot be mutated after it is taken, and it
carries ``fetched_at`` because a price is only meaningful together with the
instant it was observed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class BookLevel:
    """One resting order-book level: price as an implied probability, size in shares."""

    price: float
    size: float | None


@dataclass(frozen=True)
class Outcome:
    """One side of a binary market."""

    name: str
    clob_token_id: str | None
    implied_probability: float | None
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()


@dataclass(frozen=True)
class BinaryMarket:
    """A Polymarket binary contract as observed at ``fetched_at``.

    ``resolved_outcome`` is the label $y$: ``1`` when the first outcome won,
    ``0`` when the second did, ``None`` while unresolved, pending, or void. It
    is filled only from settlement evidence (see ``vp.venues.polymarket``),
    never from a price.
    """

    market_id: str | None
    condition_id: str | None
    slug: str | None
    question: str
    event_id: str | None
    event_title: str | None
    domain: str | None
    status: str
    trading_closed: bool
    resolution_state: str
    winning_outcome: str | None
    resolved_outcome: int | None
    end_date: str | None
    closed_time: str | None
    outcomes: tuple[Outcome, Outcome]
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    last_trade_price: float | None
    volume_usd: float | None
    liquidity_usd: float | None
    tags: tuple[str, ...]
    fetched_at: str
    parsed: dict[str, str] = field(default_factory=dict)
    fee_rate: float | None = None  # taker rate r; None when the venue did not say
    fee_exponent: float = 1.0
    market_type: str | None = None  # the venue's `sportsMarketType`, if any
    description: str | None = None  # the venue's resolution rules, verbatim
    resolution_source: str | None = None  # the URL the rules name, if any
    # Negative risk: the event's outcomes are mutually exclusive and share
    # one collateral pool; the id names that pool (docs/data_layer.md).
    neg_risk: bool = False
    neg_risk_market_id: str | None = None

    @property
    def p_yes(self) -> float | None:
        """Market-implied probability $q$ of the first outcome."""
        return self.outcomes[0].implied_probability


def _levels(raw: Any) -> tuple[BookLevel, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(
        BookLevel(price=float(lvl["implied_probability"]), size=lvl.get("size"))
        for lvl in raw
        if isinstance(lvl, dict) and "implied_probability" in lvl
    )


def market_from_record(
    record: dict[str, Any],
    *,
    event_id: str | None,
    event_title: str | None,
    tags: tuple[str, ...],
    fetched_at: str,
    domain: str | None = None,
    resolution_source: str | None = None,
) -> BinaryMarket:
    """Build a :class:`BinaryMarket` from a normalised client market record.

    Raises:
        ValueError: The record does not have exactly two outcomes or lacks a
            question; such markets are not binary contracts in the sense used
            here and are skipped by callers.
    """
    raw_outcomes = record.get("outcomes")
    if not isinstance(raw_outcomes, list) or len(raw_outcomes) != 2:
        count = len(raw_outcomes) if isinstance(raw_outcomes, list) else 0
        raise ValueError(f"expected exactly 2 outcomes, got {count}")
    question = record.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("market has no question")

    outcomes = tuple(
        Outcome(
            name=str(o.get("outcome")),
            clob_token_id=o.get("clob_token_id"),
            implied_probability=o.get("implied_probability"),
            bids=_levels((o.get("book") or {}).get("bids")),
            asks=_levels((o.get("book") or {}).get("asks")),
        )
        for o in raw_outcomes
    )
    assert len(outcomes) == 2
    resolution = record.get("resolution") or {}
    winner = resolution.get("winning_outcome")
    resolved_outcome: int | None = None
    if resolution.get("state") == "resolved" and isinstance(winner, str):
        if winner == outcomes[0].name:
            resolved_outcome = 1
        elif winner == outcomes[1].name:
            resolved_outcome = 0

    return BinaryMarket(
        market_id=record.get("market_id"),
        condition_id=record.get("condition_id"),
        slug=record.get("slug"),
        question=question.strip(),
        event_id=event_id,
        event_title=event_title,
        domain=domain,
        status=str(record.get("status")),
        trading_closed=bool(record.get("trading_closed")),
        resolution_state=str(resolution.get("state")),
        winning_outcome=winner if isinstance(winner, str) else None,
        resolved_outcome=resolved_outcome,
        end_date=record.get("end_date"),
        closed_time=record.get("closed_time"),
        outcomes=(outcomes[0], outcomes[1]),
        best_bid=record.get("best_bid"),
        best_ask=record.get("best_ask"),
        spread=record.get("spread"),
        last_trade_price=record.get("last_trade_price"),
        volume_usd=record.get("volume_usd"),
        liquidity_usd=record.get("liquidity_usd"),
        tags=tags,
        fetched_at=fetched_at,
        fee_rate=record.get("fee_rate"),
        fee_exponent=record.get("fee_exponent") or 1.0,
        market_type=record.get("market_type"),
        description=record.get("description"),
        resolution_source=record.get("resolution_source") or resolution_source,
        neg_risk=bool(record.get("neg_risk")),
        neg_risk_market_id=record.get("neg_risk_market_id"),
    )
