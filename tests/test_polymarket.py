"""Offline tests of the Polymarket client's normalisation and resolution ladder.

The fixtures follow the field names documented in ``vp.venues.polymarket``,
which upstream read off live responses. No network access is needed: these
tests pin the settlement logic, which is the part of the client that scoring
depends on. A live smoke test belongs in the Phase 7 dataset verification.
"""

from __future__ import annotations

import json

from vp.venues import polymarket as pm


def gamma_market(**overrides: object) -> dict[str, object]:
    """A Gamma market object as ``/markets/<id>`` returns it: list fields are
    JSON-encoded strings."""
    base: dict[str, object] = {
        "id": 12345,
        "question": "Will Arsenal win?",
        "slug": "will-arsenal-win",
        "conditionId": "0xabc",
        "closed": False,
        "active": True,
        "archived": False,
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.62", "0.38"]),
        "clobTokenIds": json.dumps([str(2**70), str(2**70 + 1)]),
        "bestBid": "0.61",
        "bestAsk": "0.63",
        "spread": "0.02",
        "volumeNum": 1000.5,
        "liquidityNum": "250",
        "umaResolutionStatus": None,
    }
    base.update(overrides)
    return base


def test_open_market_is_unresolved() -> None:
    market = pm.normalize_market(gamma_market())
    assert market["status"] == pm.STATUS_OPEN
    assert market["resolution"]["state"] == pm.RESOLUTION_UNRESOLVED
    assert [o["implied_probability"] for o in market["outcomes"]] == [0.62, 0.38]
    assert market["outcomes"][0]["clob_token_id"] == str(2**70)
    assert market["best_bid"] == 0.61 and market["liquidity_usd"] == 250.0


def test_closed_without_record_is_pending_with_inference_only() -> None:
    raw = gamma_market(closed=True, outcomePrices=json.dumps(["0.9999", "0.0001"]))
    market = pm.normalize_market(raw)
    assert market["status"] == pm.STATUS_CLOSED
    resolution = market["resolution"]
    assert resolution["state"] == pm.RESOLUTION_PENDING
    assert resolution["winning_outcome"] is None
    assert resolution["implied_winning_outcome"] == "Yes"


def test_uma_final_with_pinned_price_names_winner() -> None:
    raw = gamma_market(
        closed=True,
        umaResolutionStatus="resolved",
        outcomePrices=json.dumps(["0.0000004", "0.9999996"]),
    )
    market = pm.normalize_market(raw)
    assert market["status"] == pm.STATUS_RESOLVED
    assert market["resolution"]["state"] == pm.RESOLUTION_RESOLVED
    assert market["resolution"]["winning_outcome"] == "No"


def test_uma_final_split_prices_resolved_without_winner() -> None:
    raw = gamma_market(
        closed=True,
        umaResolutionStatus="settled",
        outcomePrices=json.dumps(["0.5", "0.5"]),
    )
    resolution = pm.normalize_market(raw)["resolution"]
    assert resolution["state"] == pm.RESOLUTION_RESOLVED
    assert resolution["winning_outcome"] is None


def test_uma_proposed_is_pending() -> None:
    raw = gamma_market(closed=True, umaResolutionStatus="proposed")
    assert pm.normalize_market(raw)["resolution"]["state"] == pm.RESOLUTION_PENDING


def test_pinned_price_on_open_market_is_not_settlement() -> None:
    raw = gamma_market(outcomePrices=json.dumps(["0.995", "0.005"]))
    resolution = pm.normalize_market(raw)["resolution"]
    assert resolution["state"] == pm.RESOLUTION_UNRESOLVED
    assert "implied_winning_outcome" not in resolution


def test_clob_winner_flag_outranks_everything() -> None:
    clob_payload = {
        "question": "Will Arsenal win?",
        "market_slug": "will-arsenal-win",
        "condition_id": "0xabc",
        "end_date_iso": "2026-05-24",
        "closed": True,
        "active": True,
        "archived": False,
        "tokens": [
            {"token_id": str(2**70), "outcome": "Yes", "price": "1", "winner": True},
            {
                "token_id": str(2**70 + 1),
                "outcome": "No",
                "price": "0",
                "winner": False,
            },
        ],
    }
    market = pm.normalize_market(pm._clob_market_to_gamma_shape(clob_payload))
    assert market["market_id"] is None and market["slug"] == "will-arsenal-win"
    assert market["resolution"]["state"] == pm.RESOLUTION_RESOLVED
    assert market["resolution"]["winning_outcome"] == "Yes"
    assert market["resolution"]["winning_outcome_basis"] == "clob_winner_flag"


def test_archived_status_reported_ahead_of_resolution() -> None:
    raw = gamma_market(archived=True, closed=True, umaResolutionStatus="resolved")
    market = pm.normalize_market(raw)
    assert market["status"] == pm.STATUS_ARCHIVED
    assert market["resolution"]["state"] == pm.RESOLUTION_RESOLVED


def test_event_resolution_requires_every_market_resolved() -> None:
    resolved = gamma_market(
        id=1,
        closed=True,
        umaResolutionStatus="resolved",
        outcomePrices=json.dumps(["1", "0"]),
    )
    pending = gamma_market(id=2, closed=True)
    event = {
        "id": 7,
        "title": "Arsenal fixtures",
        "closed": True,
        "markets": [resolved, pending],
    }
    record = pm.normalize_event(event, with_markets=True)
    assert record["market_count"] == 2
    assert record["resolution"]["state"] == pm.RESOLUTION_PENDING
    assert record["resolution"]["markets_resolved"] == 1
    event["markets"] = [resolved, dict(resolved, id=3)]
    assert pm.normalize_event(event, with_markets=False)["resolution"]["state"] == (
        pm.RESOLUTION_RESOLVED
    )


def test_clob_token_id_domain() -> None:
    assert pm.is_clob_token_id(str(2**63))
    assert pm.is_clob_token_id(str(2**256 - 1))
    assert not pm.is_clob_token_id(str(2**63 - 1))  # largest Gamma row id
    assert not pm.is_clob_token_id(str(2**256))
    assert not pm.is_clob_token_id("12345")
    assert not pm.is_clob_token_id("²")


def test_iter_events_walks_past_the_offset_cap(monkeypatch) -> None:
    """A tag with 2300 events is listed exactly once by restarting the walk from
    the last end date seen when the offset cap is reached."""
    events = [
        {"id": str(i), "endDate": f"2026-01-01T00:00:{i // 10:02d}Z", "markets": []}
        for i in range(2300)
    ]
    calls: list[tuple[int, str | None]] = []

    def fake_list(*, tag_id, closed, limit, offset, end_date_min=None):
        calls.append((offset, end_date_min))
        assert offset + limit <= 2000, "the cap must not be crossed"
        window = [
            e for e in events if end_date_min is None or e["endDate"] >= end_date_min
        ]
        return [
            pm.normalize_event(e, with_markets=True)
            for e in window[offset : offset + limit]
        ]

    monkeypatch.setattr(pm, "list_events", fake_list)
    ids = [e["event_id"] for e in pm.iter_events(tag_id="84", closed=True)]
    assert ids == [str(i) for i in range(2300)]
    # 20 pages at offsets 0..1900, then a restart from the boundary date.
    assert calls[19] == (1900, None)
    assert calls[20] == (0, events[1999]["endDate"])
