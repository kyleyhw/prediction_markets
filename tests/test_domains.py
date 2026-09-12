"""Domain membership and question parsing on strings recorded from the venue."""

from __future__ import annotations

from vp.domains import CS2, DOMAINS, EPL, WEATHER


def test_registry_names() -> None:
    assert sorted(DOMAINS) == ["cs2", "epl", "weather"]


def test_cs2_match_from_event_title() -> None:
    parsed = CS2.parse(
        "Spirit vs Team Falcons", "Counter-Strike: Spirit vs Team Falcons (BO3)"
    )
    assert parsed == {
        "kind": "match",
        "team_a": "Spirit",
        "team_b": "Team Falcons",
    }
    assert CS2.parse("x", "Counter-Strike: Spirit vs Team Falcons (BO3)") == {
        "kind": "match",
        "team_a": "Spirit",
        "team_b": "Team Falcons",
        "format": "BO3",
    }


def test_cs2_tournament_winner() -> None:
    assert CS2.parse("Will FURIA win the StarLadder Budapest Major 2025?", None) == {
        "kind": "tournament_winner",
        "team": "FURIA",
        "tournament": "StarLadder Budapest Major 2025",
    }


def test_cs2_membership_by_tag_and_keyword_with_exclusion() -> None:
    assert CS2.matches("Will FURIA win the StarLadder Budapest Major 2025?", None, ())
    assert CS2.matches("Who wins?", "Some event", ("Esports",))
    # "Major" alone was the archived project's false positive; it no longer admits.
    assert not CS2.matches("Will Israel launch a major ground offensive?", None, ())
    assert not CS2.matches("Counter-Strike case opening simulator?", None, ("cs2",))


def test_weather_daily_buckets() -> None:
    between = WEATHER.parse(
        "Will the highest temperature in London be between 54-55°F on December 7?", None
    )
    assert between == {
        "kind": "daily_temperature",
        "statistic": "highest",
        "city": "London",
        "date": "December 7",
        "low": "54",
        "high": "55",
        "unit": "°F",
    }
    below = WEATHER.parse(
        "Will the highest temperature in London be 53°F or below on December 7?", None
    )
    assert below is not None and (below["low"], below["high"]) == ("", "53")
    above = WEATHER.parse(
        "Will the highest temperature in London be 62°F or higher on December 8?", None
    )
    assert above is not None and (above["low"], above["high"]) == ("62", "")


def test_weather_records_and_anomaly() -> None:
    assert WEATHER.parse("Will 2025 be the hottest year on record?", None) == {
        "kind": "record_rank",
        "period": "2025",
        "rank": "1st",
        "or_lower": "false",
    }
    ranked = WEATHER.parse("Will November 2025 be the 1st hottest on record?", None)
    assert ranked is not None and ranked["rank"] == "1st"
    lower = WEATHER.parse(
        "Will 2026 rank as the sixth-hottest year on record or lower?", None
    )
    assert lower == {
        "kind": "record_rank",
        "period": "2026",
        "rank": "sixth",
        "or_lower": "true",
    }
    anomaly = WEATHER.parse(
        "Will global temperature increase by between 1.10ºC and 1.14ºC in November 2025?",
        None,
    )
    assert anomaly is not None and anomaly["kind"] == "global_anomaly"


def test_weather_exclusions_reject_sports() -> None:
    assert not WEATHER.matches("Miami Heat vs. Boston Celtics", None, ())
    assert WEATHER.matches("Will 2025 be the hottest year on record?", None, ())
    assert WEATHER.matches("anything", None, ("climate & weather",))


def test_epl_forms() -> None:
    assert EPL.parse("Will Arsenal win the 2025–26 Premier League?", None) == {
        "kind": "season_winner",
        "team": "Arsenal",
        "season": "2025–26",
    }
    assert EPL.parse("Will Arsenal win?", "Arsenal vs Chelsea") == {
        "kind": "match",
        "team_a": "Arsenal",
        "team_b": "Chelsea",
        "side": "Arsenal",
    }
    assert EPL.parse("Will the match end in a draw?", "Arsenal vs. Chelsea") == {
        "kind": "match",
        "team_a": "Arsenal",
        "team_b": "Chelsea",
        "side": "draw",
    }
    assert EPL.parse("Will Tottenham sack their manager?", None) is None
    assert EPL.matches("x", "y", ("Premier League",))
    assert not EPL.matches("EPL fantasy points?", None, ("EPL",))
