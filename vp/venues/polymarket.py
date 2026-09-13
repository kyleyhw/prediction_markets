"""Read-only Polymarket client: catalogue search, quotes, order book, history
and settlement.

Ported from HKUDS/Vibe-Trading ``agent/src/tools/prediction_market_tool.py``
(MIT); see ``NOTICE`` and ``docs/provenance.md``. The LLM-tool wrapper, its JSON
envelope and its payload caps were removed; the endpoint spec, normalisation
and the resolution-evidence ladder below are kept as written upstream, where
every field name was read off a live response.

Prediction markets quote binary event contracts: each outcome is a token that
settles at $1 if the event happens and $0 otherwise, so the live share price is
the market's *implied probability* of that outcome.

Data comes from two public, no-auth Polymarket services:

* Gamma (``https://gamma-api.polymarket.com``), catalogue and current quotes.
  - ``GET /public-search?q=&limit_per_type=&events_status=`` returns
    ``{"events": [...], "pagination": {"hasMore", "totalResults"}}``.
    ``events_status=active`` keeps only ``closed == false`` events and
    ``events_status=resolved`` only ``closed == true``; any other value is
    effectively unfiltered.
  - ``GET /events/<numeric id>`` returns one event object; a miss is HTTP 404.
  - ``GET /events?slug=<exact slug>`` returns a list (empty on a partial slug;
    the match is exact, not prefix).
  - ``GET /markets/<numeric id>`` returns one market object.
  - ``GET /events?tag_id=&closed=&limit=&offset=&order=endDate&ascending=
    &end_date_min=`` lists events by tag; ``closed`` takes ``true``/``false``.
    Measured in September 2026: ``limit`` is capped at 100 and ``offset`` at
    2000 (HTTP 422 beyond it), so deeper listing restarts from an
    ``end_date_min`` bound. Event objects carry ``tags: [{id, label, slug}]``.
  Event objects carry ``id, ticker, slug, title, description, startDate,
  endDate, closedTime, active, closed, archived, liquidity, volume,
  volume24hr, markets``. Market objects carry ``id, question, conditionId,
  slug, endDate, closed, active, archived, acceptingOrders, outcomes,
  outcomePrices, clobTokenIds, bestBid, bestAsk, lastTradePrice, spread,
  oneDayPriceChange, volumeNum, liquidityNum, closedTime, resolvedBy,
  umaResolutionStatus, umaResolutionStatuses``.

* CLOB (``https://clob.polymarket.com``), order book and price history.
  - ``GET /book?token_id=<clob token id>`` returns ``{bids, asks, asset_id,
    market, hash, last_trade_price, min_order_size, neg_risk, tick_size,
    timestamp}``. ``bids`` and ``asks`` are ``{"price", "size"}`` pairs with
    string values; bids arrive ascending and asks descending, so the *last*
    element of each is the top of book.
  - ``GET /markets/<conditionId>`` returns ``tokens: [{token_id, outcome,
    price, winner}]``. ``winner`` is the venue's own settlement flag and is the
    strongest resolution evidence either API exposes.
  - ``GET /prices-history?market=<clob token id>&interval=&fidelity=`` returns
    ``{"history": [{"t": epoch_seconds, "p": price}]}``.

Gotchas this module compensates for:

* Gamma serialises ``outcomes``, ``outcomePrices`` and ``clobTokenIds`` as JSON
  *strings*, not arrays. They are decoded before use.
* The history ``interval`` grammar is ``1h, 6h, 1d, 1w, 1m, max``, and ``1m``
  means one **month**, not one minute. ``fidelity`` is the bar width in
  *minutes*.
* ``prices-history`` is keyed by a CLOB token id (one series per outcome), not
  by the market id, so a market id has to be resolved to a token first.

Closing and resolving are two different upstream events and are kept in two
different fields. Every record carries a lifecycle ``status`` *and* a separate
``resolution`` block, and the two never substitute for each other:

* ``status``: ``open`` (trading), ``closed`` (trading ended), ``resolved``
  (trading ended *and* a resolution record exists), ``inactive``
  (``active == false``) or ``archived`` (delisted from the catalogue; reported
  ahead of the others because it describes the catalogue entry rather than the
  contract).
* ``resolution.state``: ``unresolved`` (still trading), ``pending`` (trading
  closed but nothing in the payload states the outcome) or ``resolved``.
  ``pending`` means *unknown to this client*, not *no winner*.

Evidence used for ``resolved``, strongest first, with the winner named only
when the payload actually identifies one:

1. CLOB ``tokens[].winner``: exactly one token flagged. Direct venue statement;
   available on the ``0x`` condition-id path.
2. Gamma ``umaResolutionStatus`` in ``{"resolved", "settled"}``. Observed
   values across a live sample upstream were ``null`` (702/800), ``"resolved"``
   (93), ``"settled"`` (4) and ``"proposed"`` (1); ``proposed`` means an answer
   was submitted to the oracle but is not final, so it maps to ``pending``.

Deliberately *not* treated as settlement evidence:

* ``closed == true`` on its own. It means trading ended; the upstream sample
  included pre-oracle 2020 markets closed for years with no outcome recorded.
* An outcome price at or above ``SETTLED_PRICE_FLOOR``. 115 of 400 sampled
  *open* markets had a price >= 0.99, so a pinned price is a probability, not a
  settlement. On a closed market it is reported as ``implied_winning_outcome``
  and labelled an inference; it never promotes ``state``.
* ``resolvedBy``, which is the resolver contract address and is populated on
  open markets too.
* ``active``, since a settled market keeps ``active == true``.

This module is strictly read-only: it issues GET requests against public data
endpoints only and has no order, position or account surface.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, Literal

from vp.venues._http import positive_env_float, throttled_get_json

logger = logging.getLogger(__name__)

_GAMMA_SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
_GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
_GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
_CLOB_BOOK_URL = "https://clob.polymarket.com/book"
_CLOB_MARKETS_URL = "https://clob.polymarket.com/markets"
_CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"

# Separate throttle buckets: the catalogue and the book are different hosts and
# must not share a rate budget.
_GAMMA_HOST_KEY = "polymarket_gamma"
_CLOB_HOST_KEY = "polymarket_clob"
_MIN_INTERVAL_ENV = "VP_POLYMARKET_MIN_INTERVAL"
# Polymarket publishes no rate limit for these endpoints. 0.35 s (about three
# requests per second per host) is the spacing the upstream project settled on
# without being banned; override with the environment variable for batch jobs.
_DEFAULT_MIN_INTERVAL = 0.35
_TIMEOUT_S = 20.0
# Gamma rejects ``offset`` above this with HTTP 422 ("offset too large, use
# /events/keyset for deeper pagination"); measured in September 2026.
_OFFSET_CAP = 2000

SearchStatus = Literal["open", "closed", "any"]
Interval = Literal["1h", "6h", "1d", "1w", "1m", "max"]
INTERVALS: tuple[Interval, ...] = ("1h", "6h", "1d", "1w", "1m", "max")
# Bar width in minutes per window, chosen upstream so a request lands around a
# few hundred points while keeping the window's shape readable.
_FIDELITY_MINUTES: dict[Interval, int] = {
    "1h": 1,
    "6h": 10,
    "1d": 60,
    "1w": 360,
    "1m": 1440,
    "max": 1440,
}

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_RESOLVED = "resolved"
STATUS_INACTIVE = "inactive"
STATUS_ARCHIVED = "archived"

RESOLUTION_UNRESOLVED = "unresolved"
RESOLUTION_PENDING = "pending"
RESOLUTION_RESOLVED = "resolved"

# umaResolutionStatus values that mean the oracle answer is final.
_UMA_FINAL = frozenset({"resolved", "settled"})

# An outcome price at or above this level in a closed market *implies* a winner
# but does not establish one; settled binaries print about 0.9999996 and 4e-7,
# so the floor is not tight. Used only for ``implied_winning_outcome`` and to
# name the winner once another field has established that a resolution exists.
SETTLED_PRICE_FLOOR = 0.99

# Id-space bounds used to tell a CLOB outcome token from a Gamma catalogue id.
# A CLOB token id is an ERC-1155 position id, a keccak-derived uint256 (74-78
# decimal digits in a live sample, every one above 2**63); a Gamma id is a
# sequential database row id that cannot exceed a signed 64-bit column.
_UINT256_MAX = 2**256 - 1
_MAX_DATABASE_ID = 2**63 - 1


def _get_json(url: str, *, host_key: str, params: dict[str, Any] | None = None) -> Any:
    """Throttled GET returning decoded JSON; raises on transport or HTTP error."""
    return throttled_get_json(
        url,
        host_key=host_key,
        min_interval=positive_env_float(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL),
        params=params,
        timeout=_TIMEOUT_S,
    )


def _json_list(value: Any) -> list[Any]:
    """Decode a Gamma field that may arrive as a JSON string or a real list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except ValueError, TypeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _to_float(value: Any) -> float | None:
    """Coerce a possibly-string numeric field to a finite float, else ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except ValueError, TypeError:
        return None
    return result if math.isfinite(result) else None


def _probability(value: Any) -> dict[str, float] | None:
    """Convert a raw outcome share price into a labelled probability record."""
    price = _to_float(value)
    if price is None:
        return None
    return {"implied_probability": round(price, 6)}


def is_clob_token_id(value: str) -> bool:
    """Decide whether an identifier lies in the CLOB outcome-token id domain.

    ``str.isdigit`` is true for superscripts such as ``"²"``, which ``int``
    rejects, so ASCII is checked first; both id spaces are ASCII decimal.
    """
    if not (value.isascii() and value.isdigit()):
        return False
    number = int(value)
    return _MAX_DATABASE_ID < number <= _UINT256_MAX


def _market_resolution(
    raw: dict[str, Any], outcomes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Derive a market's settlement state from resolution evidence only.

    Trading closure is never treated as settlement; see the module docstring
    for the evidence hierarchy and what is excluded from it.

    Returns:
        ``{"state", "state_basis", "winning_outcome", ...}``. ``winning_outcome``
        is non-null only when the payload names a winner; on a ``pending``
        market whose prices merely imply one, the guess travels as
        ``implied_winning_outcome`` and is labelled an inference.
    """
    names = [o.get("outcome") for o in outcomes]
    flagged = [i for i, o in enumerate(outcomes) if o.get("is_winner") is True]
    if len(flagged) == 1:
        return {
            "state": RESOLUTION_RESOLVED,
            "state_basis": (
                "clob_winner_flag: the venue flags this outcome as the winner"
            ),
            "winning_outcome": names[flagged[0]],
            "winning_outcome_basis": "clob_winner_flag",
        }

    uma_raw = raw.get("umaResolutionStatus")
    uma = (
        uma_raw.strip().lower()
        if isinstance(uma_raw, str) and uma_raw.strip()
        else None
    )
    pinned = [
        i
        for i, o in enumerate(outcomes)
        if (o.get("implied_probability") or 0.0) >= SETTLED_PRICE_FLOOR
    ]

    if uma in _UMA_FINAL:
        record: dict[str, Any] = {
            "state": RESOLUTION_RESOLVED,
            "state_basis": f"uma_resolution_status={uma}: the oracle answer is final",
        }
        if len(pinned) == 1:
            record["winning_outcome"] = names[pinned[0]]
            record["winning_outcome_basis"] = (
                "settled_outcome_price: exactly one outcome pays "
                f">= {SETTLED_PRICE_FLOOR}"
            )
        else:
            record["winning_outcome"] = None
            record["winning_outcome_basis"] = (
                "unavailable: the oracle answer is final but no single outcome "
                f"price is >= {SETTLED_PRICE_FLOOR}, which is what a void or split "
                "resolution looks like"
            )
        return record

    if raw.get("closed"):
        record = {
            "state": RESOLUTION_PENDING,
            "state_basis": (
                f"uma_resolution_status={uma}: an oracle record exists but is not final"
                if uma
                else "trading closed, and the payload carries no resolution record"
            ),
            "winning_outcome": None,
        }
        if len(pinned) == 1:
            record["implied_winning_outcome"] = names[pinned[0]]
            record["implied_winning_outcome_basis"] = (
                "INFERENCE ONLY: exactly one outcome is priced "
                f">= {SETTLED_PRICE_FLOOR} in a market whose trading has closed. "
                "This is not a settlement "
                "record and must not be reported as the resolved outcome."
            )
        return record

    if uma is not None:
        return {
            "state": RESOLUTION_PENDING,
            "state_basis": (
                f"uma_resolution_status={uma}: an oracle record exists but is not final"
            ),
            "winning_outcome": None,
        }

    return {
        "state": RESOLUTION_UNRESOLVED,
        "state_basis": "still trading: the upstream closed flag is false",
        "winning_outcome": None,
    }


def _lifecycle_status(raw: dict[str, Any], resolution_state: str) -> str:
    """Map upstream flags plus a settlement state onto one lifecycle label."""
    if raw.get("archived"):
        return STATUS_ARCHIVED
    if resolution_state == RESOLUTION_RESOLVED:
        return STATUS_RESOLVED
    if raw.get("closed"):
        return STATUS_CLOSED
    if raw.get("active") is False:
        return STATUS_INACTIVE
    return STATUS_OPEN


def _event_resolution(
    raw: dict[str, Any], markets: list[dict[str, Any]]
) -> dict[str, Any]:
    """Derive an event's settlement state from the markets beneath it.

    An event carries no prices, oracle status or winner flag of its own, so its
    only resolution evidence is its markets'. A closed event with no resolved
    market is ``pending``, never ``resolved``.
    """
    total = len(markets)
    resolved = sum(
        1
        for m in markets
        if (m.get("resolution") or {}).get("state") == RESOLUTION_RESOLVED
    )
    counts = {"markets_resolved": resolved, "markets_total": total}

    if total and resolved == total:
        return {
            "state": RESOLUTION_RESOLVED,
            "state_basis": (
                f"every one of the {total} market(s) under this event is resolved"
            ),
            **counts,
        }
    if raw.get("closed"):
        basis = (
            "trading closed; this payload exposes no markets to check"
            if not total
            else (
                f"trading closed; {resolved} of {total} markets carry a "
                "resolution record"
            )
        )
        return {"state": RESOLUTION_PENDING, "state_basis": basis, **counts}
    return {
        "state": RESOLUTION_UNRESOLVED,
        "state_basis": "still trading: the upstream closed flag is false",
        **counts,
    }


def normalize_market(raw: dict[str, Any]) -> dict[str, Any]:
    """Shape one Gamma market object (or a re-keyed CLOB one) into a market record.

    The record carries identifiers, the lifecycle ``status``, a separate
    ``resolution`` block, per-outcome implied probabilities with CLOB token
    ids, and top-of-book quote fields.
    """
    names = [str(n) for n in _json_list(raw.get("outcomes"))]
    prices = _json_list(raw.get("outcomePrices"))
    tokens = [str(t) for t in _json_list(raw.get("clobTokenIds"))]
    # Only CLOB payloads carry per-outcome winner flags; Gamma has none.
    winners = _json_list(raw.get("outcomeWinners"))

    outcomes: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        record: dict[str, Any] = {"outcome": name}
        probability = _probability(prices[index] if index < len(prices) else None)
        if probability is not None:
            record.update(probability)
        if index < len(tokens):
            record["clob_token_id"] = tokens[index]
        if index < len(winners) and isinstance(winners[index], bool):
            record["is_winner"] = winners[index]
        outcomes.append(record)

    resolution = _market_resolution(raw, outcomes)

    return {
        "market_id": str(raw.get("id")) if raw.get("id") is not None else None,
        "question": raw.get("question"),
        "slug": raw.get("slug"),
        "condition_id": raw.get("conditionId"),
        "status": _lifecycle_status(raw, resolution["state"]),
        "trading_closed": bool(raw.get("closed")),
        "resolution": resolution,
        "end_date": raw.get("endDate"),
        "closed_time": raw.get("closedTime"),
        "outcomes": outcomes,
        "volume_usd": _to_float(raw.get("volumeNum")),
        "liquidity_usd": _to_float(raw.get("liquidityNum")),
        "best_bid": _to_float(raw.get("bestBid")),
        "best_ask": _to_float(raw.get("bestAsk")),
        "spread": _to_float(raw.get("spread")),
        "last_trade_price": _to_float(raw.get("lastTradePrice")),
        "one_day_probability_change": _to_float(raw.get("oneDayPriceChange")),
    }


def normalize_event(raw: dict[str, Any], *, with_markets: bool) -> dict[str, Any]:
    """Shape one Gamma event object into an event record.

    The event's ``resolution`` is derived from its markets whether or not they
    are included in the output, since it has no other evidence to stand on.
    """
    raw_markets = raw.get("markets")
    usable = (
        [m for m in raw_markets if isinstance(m, dict)]
        if isinstance(raw_markets, list)
        else []
    )
    markets = [normalize_market(m) for m in usable]
    resolution = _event_resolution(raw, markets)

    event: dict[str, Any] = {
        "event_id": str(raw.get("id")) if raw.get("id") is not None else None,
        "title": raw.get("title"),
        "slug": raw.get("slug"),
        "ticker": raw.get("ticker"),
        "status": _lifecycle_status(raw, resolution["state"]),
        "trading_closed": bool(raw.get("closed")),
        "resolution": resolution,
        "start_date": raw.get("startDate"),
        "end_date": raw.get("endDate"),
        "closed_time": raw.get("closedTime"),
        "resolution_source": raw.get("resolutionSource"),
        "volume_usd": _to_float(raw.get("volume")),
        "volume_24h_usd": _to_float(raw.get("volume24hr")),
        "liquidity_usd": _to_float(raw.get("liquidity")),
        "tags": _tag_labels(raw.get("tags")),
        "tag_ids": _tag_ids(raw.get("tags")),
    }
    if isinstance(raw_markets, list):
        event["market_count"] = len(usable)
        if with_markets:
            event["markets"] = markets
    return event


def _tag_labels(value: Any) -> list[str]:
    """Tag labels of an event, in payload order; ``[]`` when absent."""
    if not isinstance(value, list):
        return []
    return [str(t["label"]) for t in value if isinstance(t, dict) and "label" in t]


def _tag_ids(value: Any) -> list[str]:
    """Tag ids of an event as strings, in payload order; ``[]`` when absent."""
    if not isinstance(value, list):
        return []
    return [str(t["id"]) for t in value if isinstance(t, dict) and "id" in t]


def _clob_market_to_gamma_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Re-key a CLOB market object onto the Gamma field names.

    The CLOB ``/markets/<conditionId>`` response uses snake_case and nests
    outcomes under ``tokens``. CLOB does not expose Gamma's numeric market id,
    so ``id`` stays absent and the slug travels as ``slug``. ``outcomeWinners``
    exists only on this path and outranks every other settlement signal.
    """
    tokens = [t for t in payload.get("tokens", []) if isinstance(t, dict)]
    return {
        "id": None,
        "question": payload.get("question"),
        "slug": payload.get("market_slug"),
        "conditionId": payload.get("condition_id"),
        "endDate": payload.get("end_date_iso"),
        "closed": payload.get("closed"),
        "active": payload.get("active"),
        "archived": payload.get("archived"),
        "outcomes": [str(t.get("outcome")) for t in tokens],
        "outcomePrices": [t.get("price") for t in tokens],
        "clobTokenIds": [str(t.get("token_id")) for t in tokens],
        "outcomeWinners": [t.get("winner") for t in tokens],
    }


def fetch_event(identifier: str) -> dict[str, Any]:
    """Fetch one event, with its markets, by numeric id or exact slug.

    Raises:
        ValueError: The slug matches no event, or the payload has an
            unexpected shape.
        requests.RequestException: Propagated from the HTTP layer.
    """
    if identifier.isdigit():
        payload = _get_json(
            f"{_GAMMA_EVENTS_URL}/{identifier}", host_key=_GAMMA_HOST_KEY
        )
    else:
        listed = _get_json(
            _GAMMA_EVENTS_URL, host_key=_GAMMA_HOST_KEY, params={"slug": identifier}
        )
        if not isinstance(listed, list) or not listed:
            raise ValueError(f"no event matches slug {identifier!r} (match is exact)")
        payload = listed[0]
    if not isinstance(payload, dict):
        raise ValueError("unexpected event payload shape")
    return normalize_event(payload, with_markets=True)


def fetch_book(token_id: str, *, depth: int) -> dict[str, Any]:
    """Fetch the ``depth`` levels nearest the touch of one outcome token's book.

    Returns:
        ``{"bids": [...], "asks": [...], "tick_size", "min_order_size"}`` with
        each level as ``{"implied_probability", "size"}``, best price first.

    Raises:
        ValueError: The payload has an unexpected shape.
        requests.RequestException: Propagated from the HTTP layer.
    """
    payload = _get_json(
        _CLOB_BOOK_URL, host_key=_CLOB_HOST_KEY, params={"token_id": token_id}
    )
    if not isinstance(payload, dict):
        raise ValueError("unexpected book payload shape")

    def levels(key: str) -> list[dict[str, Any]]:
        raw = payload.get(key)
        if not isinstance(raw, list):
            return []
        # Both sides arrive worst-price-first, so the touch is at the tail.
        near = [lvl for lvl in reversed(raw) if isinstance(lvl, dict)][:depth]
        out: list[dict[str, Any]] = []
        for lvl in near:
            probability = _probability(lvl.get("price"))
            if probability is None:
                continue
            level: dict[str, Any] = dict(probability)
            level["size"] = _to_float(lvl.get("size"))
            out.append(level)
        return out

    return {
        "bids": levels("bids"),
        "asks": levels("asks"),
        "tick_size": _to_float(payload.get("tick_size")),
        "min_order_size": _to_float(payload.get("min_order_size")),
    }


def fetch_market(identifier: str, *, depth: int = 0) -> dict[str, Any]:
    """Fetch one market's current quote, optionally with book depth per outcome.

    Args:
        identifier: Gamma market id (digits) or a ``0x``-prefixed condition id.
            The condition-id path goes to the CLOB and is the only one that
            carries the ``winner`` settlement flag.
        depth: Book levels per side; ``0`` skips the CLOB book round-trips.

    Raises:
        ValueError: The payload has an unexpected shape.
        requests.RequestException: Propagated from the HTTP layer.
    """
    if identifier.lower().startswith("0x"):
        payload = _get_json(
            f"{_CLOB_MARKETS_URL}/{identifier}", host_key=_CLOB_HOST_KEY
        )
        if not isinstance(payload, dict):
            raise ValueError("unexpected market payload shape")
        payload = _clob_market_to_gamma_shape(payload)
    else:
        payload = _get_json(
            f"{_GAMMA_MARKETS_URL}/{identifier}", host_key=_GAMMA_HOST_KEY
        )
    if not isinstance(payload, dict):
        raise ValueError("unexpected market payload shape")

    market = normalize_market(payload)
    if depth > 0:
        for outcome in market["outcomes"]:
            token_id = outcome.get("clob_token_id")
            if token_id:
                outcome["book"] = fetch_book(token_id, depth=depth)
    return market


def _resolve_history_token(
    identifier: str, outcome: str | None
) -> tuple[str, dict[str, Any]]:
    """Resolve a CLOB token id, condition id or Gamma market id to one token id.

    Returns:
        ``(token_id, context)`` where context carries the identifying metadata
        resolved along the way.

    Raises:
        ValueError: The id cannot be resolved to an outcome token.
        requests.RequestException: Propagated from the HTTP layer.
    """
    if is_clob_token_id(identifier):
        return identifier, {"clob_token_id": identifier}

    if identifier.lower().startswith("0x"):
        payload = _get_json(
            f"{_CLOB_MARKETS_URL}/{identifier}", host_key=_CLOB_HOST_KEY
        )
        raw = _clob_market_to_gamma_shape(payload) if isinstance(payload, dict) else {}
    else:
        raw = _get_json(f"{_GAMMA_MARKETS_URL}/{identifier}", host_key=_GAMMA_HOST_KEY)
        if not isinstance(raw, dict):
            raise ValueError("unexpected market payload shape")

    names = [str(n) for n in _json_list(raw.get("outcomes"))]
    tokens = [str(t) for t in _json_list(raw.get("clobTokenIds"))]
    if not tokens:
        raise ValueError("market exposes no CLOB outcome tokens")

    index = 0
    if outcome is not None:
        matches = [i for i, n in enumerate(names) if n.lower() == outcome.lower()]
        if not matches:
            raise ValueError(f"outcome {outcome!r} not in {names}")
        index = matches[0]
    if index >= len(tokens):
        raise ValueError("outcome has no matching CLOB token")

    return tokens[index], {
        "market_id": str(raw.get("id")) if raw.get("id") is not None else None,
        "question": raw.get("question"),
        "condition_id": raw.get("conditionId"),
        "outcome": names[index] if index < len(names) else None,
        "clob_token_id": tokens[index],
    }


def fetch_history(
    identifier: str,
    *,
    interval: Interval = "max",
    outcome: str | None = None,
    fidelity: int | None = None,
) -> dict[str, Any]:
    """Fetch one outcome's implied-probability time series.

    Args:
        identifier: CLOB token id, ``0x`` condition id, or Gamma market id.
        interval: Lookback window; ``1m`` is one month and ``max`` the full
            series. Bar width follows :data:`_FIDELITY_MINUTES` unless
            ``fidelity`` is given.
        outcome: Outcome name to select when the id names a whole market;
            defaults to the first outcome. Ignored for a CLOB token id.
        fidelity: Bar width in minutes, overriding the interval's default.
            Measured live on 2026-09-13: bars finer than daily are served
            only for markets that closed within roughly the last month
            (present from 2026-08-13, absent for 2026-08-07 and earlier);
            older markets return an empty series at ``fidelity=60`` and a
            populated one at ``1440``.

    Returns:
        Context fields plus ``interval``, ``bar_minutes`` and ``points``, each
        point ``{"timestamp": ISO-8601 UTC, "implied_probability": float}``.

    Raises:
        ValueError: The id cannot be resolved or the payload is malformed.
        requests.RequestException: Propagated from the HTTP layer.
    """
    token_id, context = _resolve_history_token(identifier, outcome)
    bar_minutes = fidelity if fidelity is not None else _FIDELITY_MINUTES[interval]
    payload = _get_json(
        _CLOB_HISTORY_URL,
        host_key=_CLOB_HOST_KEY,
        params={"market": token_id, "interval": interval, "fidelity": bar_minutes},
    )
    raw_points = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(raw_points, list):
        raise ValueError("unexpected history payload shape")

    points: list[dict[str, Any]] = []
    for entry in raw_points:
        if not isinstance(entry, dict):
            continue
        probability = _probability(entry.get("p"))
        epoch = _to_float(entry.get("t"))
        if probability is None or epoch is None:
            continue
        point: dict[str, Any] = dict(probability)
        point["timestamp"] = (
            datetime.fromtimestamp(epoch, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        points.append(point)

    return {
        **context,
        "interval": interval,
        "bar_minutes": bar_minutes,
        "points": points,
    }


def search_events(
    query: str,
    *,
    limit: int = 10,
    status: SearchStatus = "open",
    with_markets: bool = False,
) -> dict[str, Any]:
    """Search the event catalogue by keyword.

    Args:
        query: Free-text keyword(s).
        limit: Maximum events to return, passed upstream as ``limit_per_type``;
            the upstream ceiling is not documented.
        status: Filter on *trading* state. ``closed`` selects ``closed == true``
            only and cannot filter on settlement, so read each event's
            ``resolution.state``.

    Returns:
        ``{"events": [...], "total_results", "has_more", "status_filter_basis"}``
        with events normalised, including their markets when ``with_markets``.

    Raises:
        requests.RequestException: Propagated from the HTTP layer.
    """
    params: dict[str, Any] = {"q": query, "limit_per_type": limit}
    basis = "no upstream filter applied"
    if status == "open":
        params["events_status"] = "active"
        basis = "events_status=active upstream, which selects closed == false"
    elif status == "closed":
        params["events_status"] = "resolved"
        basis = (
            "events_status=resolved upstream, which selects closed == true only; "
            "it does NOT filter on settlement, so read each event's resolution.state"
        )

    payload = _get_json(_GAMMA_SEARCH_URL, host_key=_GAMMA_HOST_KEY, params=params)
    if not isinstance(payload, dict):
        return {
            "events": [],
            "total_results": 0,
            "has_more": False,
            "status_filter_basis": basis,
        }

    raw_events = payload.get("events")
    events = [
        normalize_event(e, with_markets=with_markets)
        for e in (raw_events if isinstance(raw_events, list) else [])[:limit]
        if isinstance(e, dict)
    ]
    pagination = payload.get("pagination")
    pagination = pagination if isinstance(pagination, dict) else {}
    return {
        "events": events,
        "total_results": pagination.get("totalResults"),
        "has_more": bool(pagination.get("hasMore")),
        "status_filter_basis": basis,
    }


def list_events(
    *,
    tag_id: str | None = None,
    closed: bool | None = None,
    limit: int = 100,
    offset: int = 0,
    end_date_min: str | None = None,
) -> list[dict[str, Any]]:
    """List one page of the event catalogue, optionally by tag and trading state.

    Pages are ordered by event end date, ascending, so a walk is deterministic
    and can be resumed from a date (see :func:`iter_events`).

    Args:
        tag_id: Gamma tag id to filter on; ``None`` lists across all tags.
        closed: ``True`` for events whose trading has ended, ``False`` for
            those still trading, ``None`` for both. This is a trading-state
            filter, not a settlement filter.
        limit: Page size. Measured in September 2026: the venue caps it at
            100 and silently truncates larger values.
        offset: Number of events to skip. Measured in September 2026: values
            above 2000 are rejected with HTTP 422.
        end_date_min: ISO-8601 lower bound (inclusive) on the event end date.

    Returns:
        Event records with their markets, in end-date order. An empty list
        means the page is past the end.

    Raises:
        ValueError: The payload is not a list.
        requests.RequestException: Propagated from the HTTP layer.
    """
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "order": "endDate",
        "ascending": "true",
    }
    if tag_id is not None:
        params["tag_id"] = tag_id
    if closed is not None:
        params["closed"] = "true" if closed else "false"
    if end_date_min is not None:
        params["end_date_min"] = end_date_min
    payload = _get_json(_GAMMA_EVENTS_URL, host_key=_GAMMA_HOST_KEY, params=params)
    if not isinstance(payload, list):
        raise ValueError("unexpected events payload shape")
    return [
        normalize_event(e, with_markets=True) for e in payload if isinstance(e, dict)
    ]


def iter_events(
    *, tag_id: str | None = None, closed: bool | None = None, page_size: int = 100
) -> Iterator[dict[str, Any]]:
    """Walk the catalogue in end-date order until an empty or short page ends it.

    The venue's offset cap (:data:`_OFFSET_CAP`) would stop a walk at 2000
    events, which a busy tag exceeds. When the next page would cross it, the
    walk restarts at offset 0 with ``end_date_min`` set to the last end date
    seen; events sharing that boundary date are skipped by id so none is
    yielded twice. A boundary that does not advance (more events on one end
    date than the cap) or has no end date ends the walk, since nothing past
    it can be reached this way.
    """
    seen: set[str] = set()
    offset = 0
    end_date_min: str | None = None
    while True:
        page = list_events(
            tag_id=tag_id,
            closed=closed,
            limit=page_size,
            offset=offset,
            end_date_min=end_date_min,
        )
        for event in page:
            key = event.get("event_id")
            if key in seen:
                continue
            if key is not None:
                seen.add(key)
            yield event
        if len(page) < page_size:
            return
        offset += page_size
        if offset + page_size > _OFFSET_CAP:
            boundary = page[-1].get("end_date")
            if not boundary or boundary == end_date_min:
                logger.warning("walk stopped at the offset cap, end date %s", boundary)
                return
            end_date_min, offset = boundary, 0
