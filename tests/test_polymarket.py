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


def test_fee_terms_come_from_the_markets_schedule() -> None:
    # As served on 2026-09-23 for a sports market.
    schedule = {"exponent": 1, "rate": 0.05, "takerOnly": True, "rebateRate": 0.15}
    market = pm.normalize_market(
        gamma_market(feesEnabled=True, feeSchedule=schedule, takerBaseFee=1000)
    )
    assert market["fee_rate"] == 0.05 and market["fee_exponent"] == 1.0
    encoded = gamma_market(feesEnabled=True, feeSchedule=json.dumps(schedule))
    assert pm.normalize_market(encoded)["fee_rate"] == 0.05
    assert pm.normalize_market(gamma_market(feesEnabled=False))["fee_rate"] == 0.0
    # Nothing stated is unknown, not free: the legacy base fee is not a rate.
    unknown = pm.normalize_market(gamma_market(takerBaseFee=1000))
    assert unknown["fee_rate"] is None and unknown["fee_exponent"] is None


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


def test_iter_events_follows_the_keyset_cursor_to_the_end(monkeypatch) -> None:
    """A tag with 2300 events is listed exactly once, in one pass, following
    `next_cursor` until the venue returns none."""
    events = [{"id": str(i), "markets": []} for i in range(2300)]
    calls: list[dict] = []

    def fake_get(url, *, host_key, params):
        calls.append(dict(params or {}))
        assert url.endswith("/events/keyset") and params["tag_id"] == "84"
        start = int(params.get("after_cursor", "0"))
        page = events[start : start + params["limit"]]
        nxt = start + len(page)
        return {
            "events": page,
            **({"next_cursor": str(nxt)} if nxt < len(events) else {}),
        }

    monkeypatch.setattr(pm, "_get_json", fake_get)
    ids = [e["event_id"] for e in pm.iter_events(tag_id="84", closed=True)]
    assert ids == [str(i) for i in range(2300)]
    assert len(calls) == 23 and calls[0]["closed"] == "true"
    assert "after_cursor" not in calls[0] and calls[1]["after_cursor"] == "100"


def test_resolution_payouts_name_the_winner(monkeypatch) -> None:
    rows = {
        "0xa": {
            "status": "resolved",
            "payouts": [1000000, 0],
            "resolved_at": "2026-09-20T17:52:34Z",
        },
        "0xb": {"status": "resolved", "payouts": [500000, 500000]},
        # The shape measured live on 2026-09-23: the oracle's answer as an
        # 18-decimal price, 1 for the first outcome and 0 for the second.
        "0xd": {
            "status": "resolved",
            "price": "1000000000000000000",
            "last_update_timestamp": "1767944244",
        },
        "0xe": {"status": "resolved", "price": "0"},
        "0xf": {"status": "proposed", "price": "0"},
    }

    def fake_get(url, *, host_key, params):
        row = rows.get(params["condition"])
        return {"data": [row | {"condition_id": params["condition"]}] if row else []}

    monkeypatch.setattr(pm, "_get_json", fake_get)
    a = pm.fetch_resolution("0xa")
    assert a is not None and a["winner_index"] == 0 and a["status"] == "resolved"
    b = pm.fetch_resolution("0xb")
    assert b is not None and b["winner_index"] is None  # split: no single winner
    assert pm.fetch_resolution("0xc") is None
    d = pm.fetch_resolution("0xd")
    assert d is not None and d["winner_index"] == 0
    assert d["resolved_at"] == "2026-01-09T07:37:24+00:00"
    e = pm.fetch_resolution("0xe")
    assert e is not None and e["winner_index"] == 1
    f = pm.fetch_resolution("0xf")  # proposed is not final: no answer read
    assert f is not None and f["winner_index"] is None and f["payouts"] == []


def test_history_falls_back_to_the_data_api_where_the_clob_is_retired(
    monkeypatch,
) -> None:
    import requests

    def fake_get(url, *, host_key, params):
        if "clob" in url:
            response = requests.Response()
            response.status_code = 410
            raise requests.HTTPError(response=response)
        assert params["interval"] == "max"  # the API requires a time component
        if params.get("cursor") is None:
            return {
                "data": [{"timestamp": 1788753600, "price": 0.495}],
                "pagination": {"has_more": True, "next_cursor": "c2"},
            }
        return {
            "data": [{"timestamp": 1788757200, "price": 0.5}],
            "pagination": {"has_more": False},
        }

    monkeypatch.setattr(pm, "_get_json", fake_get)
    series = pm.fetch_history(str(2**70), fidelity=60)
    assert series["source"] == "data-api-v2"
    assert [p["implied_probability"] for p in series["points"]] == [0.495, 0.5]


def test_a_token_bucket_lets_a_burst_through_then_holds_the_rate() -> None:
    import time

    from vp.venues._http import TokenBucket

    bucket = TokenBucket(rate=20.0, burst=5)
    started = time.monotonic()
    waits = [bucket.take() for _ in range(15)]
    elapsed = time.monotonic() - started
    assert waits[:5] == [0.0] * 5  # the burst
    assert 0.4 < elapsed < 0.8  # then ten more at 20 a second
