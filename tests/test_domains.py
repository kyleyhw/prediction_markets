"""Domain membership and question parsing on strings recorded from the venue."""

from __future__ import annotations

from vp.domains import CS2, DOMAINS, EPL, WEATHER


def test_registry_names() -> None:
    assert sorted(DOMAINS) == ["cs2", "epl", "weather"]


def test_cs2_match_forms() -> None:
    # Live September 2026 form: the question is the event title, with the
    # series format in parentheses and the stage after a dash.
    title = "Counter-Strike: Rare Atom vs DEPO (BO3) - Asia Championships Closed Qualifier Playoffs"
    assert CS2.parse(title, title) == {
        "kind": "match",
        "team_a": "Rare Atom",
        "team_b": "DEPO",
        "format": "BO3",
        "stage": "Asia Championships Closed Qualifier Playoffs",
    }
    # Per-map winner: no format in the question, so it is read from the title.
    assert CS2.parse(
        "Counter-Strike: G2 vs Legacy - Map 1 Winner",
        "Counter-Strike: G2 vs Legacy (BO3) - IEM",
    ) == {
        "kind": "match",
        "team_a": "G2",
        "team_b": "Legacy",
        "format": "BO3",
        "map": "1",
    }
    # 2024 form with the stage before the colon, and the short "CS:" prefix.
    assert CS2.parse("ESL Counter-Strike Quarterfinals: G2 vs Liquid", None) == {
        "kind": "match",
        "team_a": "G2",
        "team_b": "Liquid",
    }
    assert CS2.parse("CS: Sashi vs HOTU", None) == {
        "kind": "match",
        "team_a": "Sashi",
        "team_b": "HOTU",
    }
    # Props under a match event are binary but not match-winner contracts.
    match_title = "Counter-Strike: STATE vs B8 Academy (BO3) - United21 Playoffs"
    assert CS2.parse("Games Total: O/U 2.5", match_title) is None
    assert (
        CS2.parse("Map Handicap: STA (-1.5) vs B8 Academy (+1.5)", match_title) is None
    )
    assert CS2.parse("Map 1: Odd/Even Total Kills?", match_title) is None


def test_cs2_tournament_winner() -> None:
    assert CS2.parse("Will FURIA win the StarLadder Budapest Major 2025?", None) == {
        "kind": "tournament_winner",
        "team": "FURIA",
        "tournament": "StarLadder Budapest Major 2025",
    }
    assert CS2.parse("Will M80 win ESL Challenger Atlanta 2024?", None) == {
        "kind": "tournament_winner",
        "team": "M80",
        "tournament": "ESL Challenger Atlanta 2024",
    }
    # Not a named tournament.
    assert CS2.parse("Will FaZe win a Tier 1 event in 2026?", None) is None


def test_cs2_membership_by_tag_and_keyword_with_exclusion() -> None:
    assert CS2.matches("Will FURIA win the StarLadder Budapest Major 2025?", None, ())
    assert CS2.matches("Who wins?", "Some event", ("CS2",))
    # The Esports label is shared with other games and no longer admits.
    assert not CS2.matches("Who wins?", "Some event", ("Esports",))
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
    # Live September 2026 form: a one-degree bucket with no range word.
    exact = WEATHER.parse(
        "Will the highest temperature in Cape Town be 17°C on September 12?", None
    )
    assert exact is not None and (exact["low"], exact["high"], exact["unit"]) == (
        "17",
        "17",
        "°C",
    )


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


def test_epl_season_forms() -> None:
    # Live September 2026 and 2024 forms; the archived Bundesliga analogy still parses.
    assert EPL.parse(
        "Will Arsenal win the 2026-27 English Premier League (EPL) Championship?", None
    ) == {
        "kind": "season_winner",
        "team": "Arsenal",
        "season": "2026-27",
    }
    assert EPL.parse(
        "Will Man City win the Premier League?", "Premier League Winner"
    ) == {
        "kind": "season_winner",
        "team": "Man City",
        "season": "",
    }
    assert EPL.parse("Will Arsenal win the 2025–26 Premier League?", None) == {
        "kind": "season_winner",
        "team": "Arsenal",
        "season": "2025–26",
    }


def test_epl_match_forms() -> None:
    fixture = "Brighton & Hove Albion FC vs. Arsenal FC"
    assert EPL.parse("Will Arsenal FC win on 2026-09-19?", fixture) == {
        "kind": "match",
        "team_a": "Brighton & Hove Albion FC",
        "team_b": "Arsenal FC",
        "side": "Arsenal FC",
        "date": "2026-09-19",
    }
    assert EPL.parse(f"Will {fixture} end in a draw?", fixture) == {
        "kind": "match",
        "team_a": "Brighton & Hove Albion FC",
        "team_b": "Arsenal FC",
        "side": "draw",
    }
    # 2024 forms, with a trailing space in the recorded title.
    assert EPL.parse("Will PSG win against Barcelona?", "PSG vs Barcelona ") == {
        "kind": "match",
        "team_a": "PSG",
        "team_b": "Barcelona",
        "side": "PSG",
    }
    assert EPL.parse("Will PSG vs Barcelona be a draw?", "PSG vs Barcelona ") == {
        "kind": "match",
        "team_a": "PSG",
        "team_b": "Barcelona",
        "side": "draw",
    }
    assert EPL.parse(
        "Will the match between Tottenham and Liverpool end in a draw?", None
    ) == {
        "kind": "match",
        "team_a": "Tottenham",
        "team_b": "Liverpool",
        "side": "draw",
    }
    # A prop under a fixture is not a match-winner contract; other league
    # questions are members without structured fields.
    assert (
        EPL.parse(
            "Arsenal FC vs. Chelsea FC: O/U 2.5",
            "Arsenal FC vs. Chelsea FC - More Markets",
        )
        is None
    )
    assert (
        EPL.parse("Will Erling Haaland be the top goalscorer in the EPL", None) is None
    )
    assert EPL.parse("Will Tottenham sack their manager?", None) is None


def test_epl_membership_excludes_other_competitions() -> None:
    assert EPL.matches(
        "Will Arsenal FC win on 2026-09-19?",
        "Brighton & Hove Albion FC vs. Arsenal FC",
        ("EPL", "Premier League"),
    )
    assert EPL.matches("x", "y", ("Premier League",))
    assert not EPL.matches("EPL fantasy points?", None, ("EPL",))
    # Tag 306 was applied to European ties in 2024, and tag 82 carries qualification markets.
    assert not EPL.matches(
        "Champions League: Arsenal vs Bayern Munich",
        "Champions League: Arsenal vs Bayern Munich",
        ("EPL",),
    )
    assert not EPL.matches(
        "Will Arsenal qualify for the 2027-28 UEFA Champions League?",
        "EPL: Team to qualify for the 2027-28 UEFA Champions League",
        ("Premier League",),
    )
    assert not EPL.matches(
        "Will Arsenal WFC win on 2026-09-13?",
        "Arsenal WFC vs. Crystal Palace",
        ("Premier League",),
    )
