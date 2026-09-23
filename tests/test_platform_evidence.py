"""The evidence collectors, against canned answers from each source."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tests.conftest import needs_db
from vp.platform import evidence
from vp.platform.storage import LocalStore


def test_the_season_turns_over_in_august() -> None:
    assert evidence.season(datetime(2026, 9, 23, tzinfo=UTC)) == "2026-27"
    assert evidence.season(datetime(2027, 5, 1, tzinfo=UTC)) == "2026-27"
    assert evidence.season(datetime(2026, 7, 31, tzinfo=UTC)) == "2025-26"


CANNED = {
    "open_meteo_geocode": {
        "results": [
            {
                "latitude": 36.7,
                "longitude": 117.0,
                "timezone": "Asia/Shanghai",
                "country_code": "CN",
            }
        ]
    },
    "open_meteo": {
        "latitude": 36.7,
        "longitude": 117.0,
        "timezone": "Asia/Shanghai",
        "daily": {
            "time": ["2026-09-23", "2026-09-24"],
            "temperature_2m_max": [25.1, 24.0],
            "temperature_2m_min": [15.0, 14.2],
        },
    },
    "github_raw": {
        "name": "English Premier League 2026/27",
        "matches": [
            {
                "round": "Matchday 1",
                "date": "2026-08-15",
                "team1": "A",
                "team2": "B",
                "score": {"ft": [1, 0]},
            },
            {"round": "Matchday 6", "date": "2026-09-27", "team1": "C", "team2": "D"},
        ],
    },
    "gdelt": {
        "articles": [
            {
                "title": "Heatwave",
                "url": "https://example.test/a",
                "seendate": "20260923T100000Z",
                "domain": "example.test",
                "language": "English",
            }
        ]
    },
}


@needs_db
def test_each_source_writes_a_capture_with_its_time(
    app_pool, pg_owner, monkeypatch, tmp_path: Path
) -> None:
    with pg_owner.transaction():
        pg_owner.execute("delete from tracked_markets")
        pg_owner.execute("delete from evidence_captures")
        pg_owner.execute(
            "insert into tracked_markets (market_id, domain, question, tokens, record) values "
            "('w1', 'weather', 'Will the highest temperature in Jinan be 25°C?', '{}', "
            """'{"parsed": [["kind", "daily_temperature"], ["city", "Jinan"]]}'), """
            "('e1', 'epl', 'Arsenal vs Chelsea', '{}', '{}')"
        )
    calls: list[str] = []

    def fake_get(url, host, params=None):
        calls.append(host)
        return CANNED[host]

    monkeypatch.setattr(evidence, "_get", fake_get)
    store = LocalStore(tmp_path / "store")
    assert evidence.weather_cities(app_pool) == ["Jinan"]
    results = {name: fn(store, app_pool) for name, fn in evidence.SOURCES.items()}
    assert results["open_meteo"]["rows"] == 2
    assert results["openfootball"]["rows"] == 2
    assert results["venue_schedules"]["rows"] == 2
    assert results["gdelt"]["rows"] == 3  # one canned article per domain query
    table = pq.read_table(tmp_path / "store" / results["open_meteo"]["key"])
    row = table.to_pylist()[0]
    assert (
        row["city"] == "Jinan"
        and row["captured_at"].endswith("Z")
        and row["lead_days"] == 0
    )
    # Coordinates are cached: a second run does not geocode again.
    calls.clear()
    evidence.open_meteo(store, app_pool)
    assert calls == ["open_meteo"]
    (n,) = pg_owner.execute("select count(*) from evidence_captures").fetchone()
    assert n == 5


def test_a_failing_source_does_not_stop_the_others(monkeypatch) -> None:
    from types import SimpleNamespace

    def boom(store, pool):
        raise RuntimeError("source down")

    monkeypatch.setattr(
        evidence, "SOURCES", {"bad": boom, "good": lambda s, p: {"rows": 1}}
    )
    ctx = SimpleNamespace(
        job=SimpleNamespace(payload={}),
        services=SimpleNamespace(store=None),
        pool=None,
        progress=lambda *a: None,
    )
    result = evidence.collect_evidence(ctx)  # ty: ignore[invalid-argument-type]
    assert result["good"] == {"rows": 1} and "source down" in result["bad"]["error"]
    with pytest.raises(KeyError):
        evidence.SOURCES["missing"]


def test_headline_queries_come_from_each_domain_s_keywords() -> None:
    from vp.domains import DOMAINS

    for adapter in DOMAINS.values():
        query = evidence.headline_query(adapter)
        assert query and all(
            f'"{w}"' in query for w in query.strip('"').split('" OR "')
        )
