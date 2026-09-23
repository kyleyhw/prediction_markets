"""The evidence archive: rows are served only once visible, a tampered
capture is not read, only a point-in-time source may backfill, weather
markets name their station, and the weather-model signals use what was
issued before the cutoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vp.domains.weather import station
from vp.forecast.archive import Archive, write_capture
from vp.forecast.evidence import Evidence
from vp.signals import gates, registry
from vp.sources.open_meteo import daily_rows


@pytest.fixture(scope="module")
def roots(tmp_path_factory: pytest.TempPathFactory):
    return gates.fixtures(tmp_path_factory.mktemp("archive"))


def test_rows_are_served_only_once_visible(tmp_path) -> None:
    c = gates.CUTOFF
    write_capture(tmp_path, "gdelt", [{"title": "a"}], provenance={}, now=c)
    write_capture(
        tmp_path,
        "open_meteo_runs",
        [{"day": "x", "available_at": (c - timedelta(days=3)).isoformat()}],
        provenance={},
        now=c + timedelta(days=30),  # fetched later, issued before
    )
    archive = Archive(tmp_path)
    assert archive.rows("gdelt", c) == []  # captured at the cutoff: not before it
    assert len(archive.rows("gdelt", c + timedelta(seconds=1))) == 1
    assert len(archive.rows("open_meteo_runs", c)) == 1
    with pytest.raises(ValueError, match="not a point-in-time source"):
        write_capture(tmp_path, "gdelt", [{"available_at": "x"}], provenance={})


def test_a_capture_that_does_not_match_its_manifest_is_not_read(tmp_path) -> None:
    path = write_capture(
        tmp_path, "gdelt", [{"title": "a"}], provenance={"q": 1}, now=gates.CUTOFF
    )
    assert path is not None
    manifest = path.with_suffix(".json").read_text()
    assert '"licence": "GDELT' in manifest and '"q": 1' in manifest
    other = write_capture(
        tmp_path / "x", "gdelt", [{"title": "b"}], provenance={}, now=gates.CUTOFF
    )
    assert other is not None
    path.write_bytes(other.read_bytes())
    assert Archive(tmp_path).rows("gdelt", gates.CUTOFF + timedelta(days=1)) == []


def test_weather_markets_name_their_station() -> None:
    assert station("https://www.weather.gov/wrh/timeseries?site=eglc") == "EGLC"
    assert (
        station("https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA")
        == "KLGA"
    )
    assert station(None) is None and station("https://example.com/x") is None


def test_previous_runs_become_local_days_with_their_issue_bound() -> None:
    hours = [f"2026-03-29T{h:02d}:00" for h in range(24)]  # the clocks go forward
    data = {
        "timezone": "Europe/London",
        "hourly": {
            "time": hours,
            "temperature_2m_previous_day1": [10.0 + h / 2 for h in range(24)],
            "temperature_2m_previous_day2": [None] * 24,
        },
    }
    site = {"station": "EGLC", "latitude": 51.5, "longitude": 0.05}
    (row,) = daily_rows(site, data, (1, 2))  # a day with no values is dropped
    assert row["tmax"] == 21.5 and row["tmin"] == 10.0
    # 23:00 BST is 22:00 UTC; a day earlier plus six hours of delivery.
    assert row["available_at"] == "2026-03-29T04:00:00+00:00"


def test_the_weather_model_signals_read_what_was_issued_before(roots) -> None:
    plain, guarded = roots
    targets = [t for t in plain.targets if t.event_id == "wtarget"]
    a, b = Evidence(gates.CUTOFF, plain.root), Evidence(gates.CUTOFF, guarded.root)
    forecast, ensemble = registry.load("nwp_forecast"), registry.load("nwp_ensemble")
    p = [forecast.compute(t, a) for t in targets]
    assert all(v is not None for v in p) and sum(v or 0 for v in p) == pytest.approx(1)
    # The forecast was 19 and the station reads one degree above: 20-21.
    assert max(range(4), key=lambda i: p[i] or 0) == 2
    assert p == [forecast.compute(t, b) for t in targets]
    e = [ensemble.compute(t, a) for t in targets]
    assert all(v is not None for v in e) and e == [
        ensemble.compute(t, b) for t in targets
    ]
    assert [h.title for h in a.headlines(targets[0].domain or "")] == ["Heat at 20.0"]
    later = Evidence(gates.CUTOFF + timedelta(hours=2), guarded.root)
    assert [h.title for h in later.headlines(targets[0].domain or "")][0] == (
        "Heat at 40.0"
    )


def test_the_llm_forecaster_reads_the_archive_through_its_tools(roots) -> None:
    from vp.forecast.llm import TOOLS, run_tool

    plain, _ = roots
    ev = Evidence(gates.CUTOFF, plain.root)
    target = next(t for t in plain.targets if t.event_id == "wtarget")
    assert {"weather_forecast", "league_table", "headlines"} <= {
        t["name"] for t in TOOLS
    }
    text = run_tool("weather_forecast", {}, target, ev)
    assert "issued 3 day(s) ahead" in text and "observed highest" in text
    assert "Heat at 20.0" in run_tool(
        "headlines", {"hours": 24, "limit": 5}, target, ev
    )
    assert "no records" in run_tool("league_table", {}, target, ev)


def test_the_table_counts_only_results_known_before_the_cutoff(tmp_path) -> None:
    from vp.sources.openfootball import rows

    data = {
        "name": "League 2025/26",
        "matches": [
            {
                "date": "2025-08-16",
                "time": "15:00",
                "team1": "A FC",
                "team2": "B FC",
                "score": {"ft": [2, 0]},
            },
            {
                "date": "2025-08-23",
                "time": "15:00",
                "team1": "B FC",
                "team2": "A FC",
                "score": [1, 1],
            },
            {"date": "2025-08-30", "time": "15:00", "team1": "A FC", "team2": "B FC"},
        ],
    }
    later = datetime(2026, 9, 1, tzinfo=UTC)  # fetched long after
    write_capture(
        tmp_path,
        "openfootball",
        rows(data, "lg", "Europe/London"),
        provenance={},
        now=later,
    )
    first = Evidence(datetime(2025, 8, 16, 16, 30, tzinfo=UTC), tmp_path)
    assert first.table("lg") == []  # kick-off 14:00 UTC: known from 17:00
    second = Evidence(datetime(2025, 8, 24, tzinfo=UTC), tmp_path)
    (a, b) = second.table("lg")
    assert (a.team, a.played, a.points, b.points) == ("a", 2, 4, 1)
