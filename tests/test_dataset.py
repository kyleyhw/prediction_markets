"""Dataset building and snapshot collection against a fake Polymarket source.

The fake serves normalised event records shaped like the client's output,
so these tests cover discovery de-duplication, domain filtering, the
classification counts in the report, and the files written.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from vp.domains import CS2, EPL
from vp.markets import store
from vp.markets.dataset import build_resolved_dataset
from vp.markets.polymarket import PolymarketSource
from vp.markets.snapshot import collect_snapshot


def market(
    market_id: str, question: str, *, closed: bool, state: str, winner: str | None
) -> dict[str, Any]:
    return {
        "market_id": market_id,
        "condition_id": f"0x{market_id}",
        "slug": None,
        "question": question,
        "status": "resolved"
        if state == "resolved"
        else ("closed" if closed else "open"),
        "trading_closed": closed,
        "resolution": {"state": state, "winning_outcome": winner},
        "end_date": None,
        "closed_time": None,
        "outcomes": [
            {
                "outcome": "Yes",
                "clob_token_id": f"{market_id}0",
                "implied_probability": 0.5,
            },
            {
                "outcome": "No",
                "clob_token_id": f"{market_id}1",
                "implied_probability": 0.5,
            },
        ],
    }


EPL_EVENT = {
    "event_id": "10",
    "title": "Premier League Winner 2025-26",
    "tags": ("Premier League", "Soccer"),
    "markets": [
        market(
            "1",
            "Will Arsenal win the 2025–26 Premier League?",
            closed=True,
            state="resolved",
            winner="Yes",
        ),
        market(
            "2",
            "Will Chelsea win the 2025–26 Premier League?",
            closed=True,
            state="resolved",
            winner="No",
        ),
        market(
            "3",
            "Will Spurs win the 2025–26 Premier League?",
            closed=True,
            state="resolved",
            winner="Yes",
        ),
        market(
            "8",
            "Will Villa win the 2025–26 Premier League?",
            closed=True,
            state="resolved",
            winner=None,
        ),
        market(
            "4",
            "Will Everton win the 2025–26 Premier League?",
            closed=True,
            state="pending",
            winner=None,
        ),
        market(
            "5",
            "Will Leeds win the 2025–26 Premier League?",
            closed=False,
            state="unresolved",
            winner=None,
        ),
    ],
}
CS2_EVENT = {
    "event_id": "20",
    "title": "Counter-Strike: Spirit vs Team Falcons (BO3)",
    "tags": ("Esports",),
    "markets": [
        market(
            "6", "Spirit vs Team Falcons", closed=False, state="unresolved", winner=None
        )
    ],
}
OTHER_EVENT = {
    "event_id": "30",
    "title": "Fed decision",
    "tags": ("Fed Rates",),
    "markets": [
        market(
            "7", "Will the Fed cut rates?", closed=True, state="resolved", winner="Yes"
        )
    ],
}

CALLS: list[str] = []


def fake_iter_events(
    *, tag_id: str | None, closed: bool | None, page_size: int = 100
) -> Iterator[dict[str, Any]]:
    CALLS.append(f"iter:{tag_id}:{closed}")
    if tag_id == "306":
        yield EPL_EVENT


def fake_search(
    query: str, *, limit: int, status: str, with_markets: bool
) -> dict[str, Any]:
    CALLS.append(f"search:{query}:{status}")
    events = [EPL_EVENT, CS2_EVENT, OTHER_EVENT]
    return {"events": events, "total_results": len(events), "has_more": False}


HISTORY_CALLS: list[tuple[str, int | None]] = []


def fake_history(
    token_id: str, *, interval: str, fidelity: int | None = None
) -> dict[str, Any]:
    """Token "10" is empty at every bar width; "20" fails; "30" is served only
    at daily bars, as the venue does for older markets; the rest are hourly."""
    HISTORY_CALLS.append((token_id, fidelity))
    if token_id == "20":
        raise RuntimeError("HTTP 404")
    served = token_id != "10" and (token_id != "30" or fidelity == 1440)
    points = (
        [{"timestamp": "2026-01-01T00:00:00Z", "implied_probability": 0.3}]
        if served
        else []
    )
    return {
        "clob_token_id": token_id,
        "interval": interval,
        "bar_minutes": fidelity,
        "points": points,
    }


def fake_book(token_id: str, *, depth: int) -> dict[str, Any]:
    return {
        "bids": [{"implied_probability": 0.49, "size": 5.0}][:depth],
        "asks": [{"implied_probability": 0.51, "size": 7.0}][:depth],
    }


def make_source() -> PolymarketSource:
    return PolymarketSource(
        iter_events=fake_iter_events,
        search_events=fake_search,
        fetch_history=fake_history,
        fetch_book=fake_book,
        now=lambda: "2026-09-12T00:00:00Z",
    )


def test_discover_dedupes_and_filters() -> None:
    CALLS.clear()
    found = list(make_source().discover(EPL, closed=None))
    # The EPL event arrives via the tag page and again via every keyword search;
    # each market is yielded once, and the CS2 and Fed markets are excluded.
    assert sorted(m.market_id or "" for m in found) == ["1", "2", "3", "4", "5", "8"]
    assert all(m.domain == "epl" and m.parsed["kind"] == "season_winner" for m in found)
    assert "iter:82:None" in CALLS
    assert "iter:306:None" in CALLS and "search:premier league:open" in CALLS


def test_build_resolved_dataset(tmp_path: Path) -> None:
    HISTORY_CALLS.clear()
    report = build_resolved_dataset(EPL, make_source(), tmp_path)
    assert (report.markets_seen, report.resolved_with_label) == (6, 3)
    assert (report.resolved_void, report.pending, report.still_open) == (1, 1, 1)
    # Market 1's token "10" is empty at both bar widths; market 2's token "20"
    # fails; market 3's token "30" is empty at hourly bars and served at daily.
    assert report.histories_fetched == 2 and report.histories_empty == 1
    assert report.history_errors == [("2", "HTTP 404")]
    assert report.histories_by_bar == {1440: 1}
    assert HISTORY_CALLS == [
        ("10", 60),
        ("10", 1440),
        ("20", 60),
        ("30", 60),
        ("30", 1440),
    ]
    saved = store.read_markets(tmp_path / "markets" / "epl" / "resolved.parquet")
    assert [m.resolved_outcome for m in saved] == [1, 0, 1]
    assert (tmp_path / "histories" / "epl" / "1.parquet").exists()
    assert not (tmp_path / "histories" / "epl" / "2.parquet").exists()
    daily = store.read_history(tmp_path / "histories" / "epl" / "3.parquet")
    assert [row["bar_minutes"] for row in daily] == [1440]
    assert "resolved with a label: 3" in report.summary()
    assert "served at 1440-minute bars: 1" in report.summary()


def test_build_respects_max_markets(tmp_path: Path) -> None:
    report = build_resolved_dataset(
        EPL, make_source(), tmp_path, max_markets=1, with_history=False
    )
    assert report.resolved_with_label == 1 and report.histories_fetched == 0


def test_snapshot_attaches_books(tmp_path: Path) -> None:
    path, count = collect_snapshot(CS2, make_source(), tmp_path, depth=1)
    assert count == 1 and path.parent == tmp_path / "snapshots" / "cs2"
    saved = store.read_markets(path)
    assert saved[0].parsed["kind"] == "match"
    assert saved[0].outcomes[0].asks[0].price == 0.51
    assert saved[0].outcomes[1].bids[0].size == 5.0
