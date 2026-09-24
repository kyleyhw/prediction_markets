"""A public address's record as bets (docs/shadow.md, task 92).

The venue's activity is a list of fills. A **bet** is one outcome of one
market with all its buys aggregated (VWAP entry, total stake, first entry)
and its sells subtracted. Conditions touched by a split, merge or
conversion are set aside: those are market making or negative-risk
bookkeeping, not directional bets, and their fills do not add up to one.

Outcomes come only from settlement evidence: our dataset's label, or the
venue's resolution record. A closed market without either is unscored.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from vp.markets.schema import BinaryMarket

NON_DIRECTIONAL = {"SPLIT", "MERGE", "CONVERSION"}
Series = list[tuple[float, float]]  # (epoch seconds, price of the bet's side)


def _at(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


@dataclass
class Bet:
    condition_id: str
    token_id: str
    outcome_index: int
    outcome: str
    title: str
    event_slug: str
    first_at: datetime
    last_at: datetime
    fills: int = 0
    bought: float = 0.0  # shares
    cost: float = 0.0  # USD paid for them
    sold: float = 0.0
    proceeds: float = 0.0
    sells: int = 0
    # Attached from the market and the venue.
    domain: str | None = None
    parsed: dict[str, str] = field(default_factory=dict)
    fee_rate: float | None = None
    fee_exponent: float = 1.0
    won: bool | None = None
    closed_at: datetime | None = None  # settlement, as the backtest measures it
    line_at: datetime | None = None  # the event's scheduled time: the line closes
    favourite: bool | None = None  # the side priced at or above one half at entry
    close: float | None = None
    before: float | None = None  # price 24 hours before the first buy
    series: Series = field(default_factory=list)

    @property
    def entry(self) -> float:
        return self.cost / self.bought if self.bought else 0.0

    @property
    def held(self) -> float:
        return max(self.bought - self.sold, 0.0)

    @property
    def scored(self) -> bool:
        return self.won is not None and self.bought > 0

    @property
    def payout(self) -> float:
        return self.proceeds + (self.held if self.won else 0.0)

    @property
    def pnl(self) -> float:
        return self.payout - self.cost

    @property
    def hours_before_close(self) -> float | None:
        if self.closed_at is None:
            return None
        return (self.closed_at - self.first_at).total_seconds() / 3600

    def price_at(self, when: datetime) -> float | None:
        """The last price of the bet's side at or before ``when``."""
        t = when.timestamp()
        last = None
        for at, p in self.series:
            if at > t:
                break
            last = p
        return last


@dataclass
class Record:
    address: str
    bets: list[Bet]
    events: dict[str, int]  # activity counts by type
    set_aside: list[str]  # conditions with splits, merges or conversions
    first_at: datetime | None
    last_at: datetime | None
    truncated: bool  # the activity cap was reached; the oldest is missing

    def scored(self) -> list[Bet]:
        return [b for b in self.bets if b.scored]


def build(address: str, activity: Iterable[Mapping[str, Any]], cap: int) -> Record:
    """Bets from the venue's activity rows (any order)."""
    rows = list(activity)
    events = Counter(str(r.get("type") or "") for r in rows)
    aside = {
        str(r.get("condition_id")) for r in rows if r.get("type") in NON_DIRECTIONAL
    }
    bets: dict[str, Bet] = {}
    for r in sorted(rows, key=lambda r: float(r.get("timestamp") or 0)):
        if r.get("type") != "TRADE" or r.get("condition_id") in aside:
            continue
        token, at = str(r.get("token_id")), _at(float(r["timestamp"]))
        size, usd = float(r.get("size") or 0), float(r.get("usdc_size") or 0)
        bet = bets.get(token)
        if bet is None:
            bet = bets[token] = Bet(
                condition_id=str(r.get("condition_id")),
                token_id=token,
                outcome_index=int(r.get("outcome_index") or 0),
                outcome=str(r.get("outcome") or ""),
                title=str(r.get("title") or ""),
                event_slug=str(r.get("event_slug") or ""),
                first_at=at,
                last_at=at,
            )
        bet.last_at = at
        if r.get("side") == "BUY":
            bet.fills += 1
            bet.bought += size
            bet.cost += usd
        else:
            bet.sells += 1
            bet.sold += size
            bet.proceeds += usd
    # A sell of shares never bought here came from elsewhere (a transfer).
    kept = [b for b in bets.values() if b.bought > 0 and b.sold <= b.bought * 1.0001]
    stamps = [float(r["timestamp"]) for r in rows if r.get("timestamp")]
    return Record(
        address=address.lower(),
        bets=sorted(kept, key=lambda b: b.first_at),
        events=dict(events),
        set_aside=sorted(aside),
        first_at=_at(min(stamps)) if stamps else None,
        last_at=_at(max(stamps)) if stamps else None,
        truncated=len(rows) >= cap,
    )


def _time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _closed(market: BinaryMarket) -> datetime | None:
    """When the result became known, as the backtest reads it (`settled_at`)."""
    return _time(market.closed_time) or _time(market.end_date)


def _line(market: BinaryMarket) -> datetime | None:
    """When the betting line closes: the event's scheduled time (kickoff, the
    match, the day measured). Trading often runs on past it, and a price read
    after the event is its result, not a line (measured 2026-09-24)."""
    return _time(market.end_date) or _time(market.closed_time)


def attach(
    record: Record,
    markets: Mapping[str, BinaryMarket],
    resolve: Callable[[str], dict[str, Any] | None],
    history: Callable[[str], Series],
    *,
    max_histories: int = 300,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, int]:
    """Attach each bet's domain, outcome, close and prices; returns counts.

    ``markets`` maps condition ids to our dataset's records; ``resolve``
    asks the venue for a condition's settlement; ``history`` gives a
    token's price series. Histories are fetched for the newest
    ``max_histories`` scored bets only.
    """
    asked: dict[str, dict[str, Any] | None] = {}
    for bet in record.bets:
        market = markets.get(bet.condition_id)
        if market is not None:
            bet.domain, bet.parsed = market.domain, dict(market.parsed)
            bet.fee_rate, bet.fee_exponent = market.fee_rate, market.fee_exponent
            bet.closed_at, bet.line_at = _closed(market), _line(market)
            first = market.outcomes[0].clob_token_id == bet.token_id
            if market.resolved_outcome is not None:
                bet.won = (market.resolved_outcome == 1) == first
                continue
        if bet.condition_id not in asked:
            asked[bet.condition_id] = resolve(bet.condition_id)
        settled = asked[bet.condition_id]
        if settled and settled.get("winner_index") is not None:
            bet.won = settled["winner_index"] == bet.outcome_index
            if bet.closed_at is None and settled.get("resolved_at"):
                bet.closed_at = datetime.fromisoformat(
                    str(settled["resolved_at"]).replace("Z", "+00:00")
                )
    scored = sorted(record.scored(), key=lambda b: b.first_at, reverse=True)
    wanted = scored[:max_histories]
    for i, bet in enumerate(wanted):
        if progress:
            progress(i / max(len(wanted), 1), f"prices {i + 1} of {len(wanted)}")
        try:
            bet.series = history(bet.token_id)
        except Exception:  # noqa: BLE001 - a missing series leaves the bet unpriced
            continue
        # Only where the event's time is known: a settlement time alone would
        # read the result as the close.
        if bet.line_at is not None:
            bet.close = bet.price_at(min(bet.line_at, bet.closed_at or bet.line_at))
        bet.before = bet.price_at(bet.first_at - timedelta(hours=24))
        at_entry = bet.price_at(bet.first_at)
        bet.favourite = (at_entry if at_entry is not None else bet.entry) >= 0.5
    for bet in record.bets:
        if bet.favourite is None:
            bet.favourite = bet.entry >= 0.5
    return {
        "bets": len(record.bets),
        "scored": len(scored),
        "priced": sum(1 for b in wanted if b.close is not None),
        "in_domains": sum(1 for b in record.bets if b.domain),
        "resolutions_asked": len(asked),
    }
