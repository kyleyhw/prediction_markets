"""The strategy spec, its rendering and diff, and what runs it (Phase 15)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from vp.backtest.sizing import FeeModel, Policy
from vp.domains import DOMAINS, props
from vp.markets.schema import BinaryMarket, Outcome
from vp.paper.ledger import Ledger
from vp.paper.loop import run_cycle
from vp.strategy import run
from vp.strategy.spec import Caps, Spec, canonical, diff, render, spec_hash, validate

FIXTURE = Path(__file__).parent / "fixtures" / "props.json"


def make_market(**fields) -> BinaryMarket:
    base: dict[str, Any] = dict(
        market_id="m",
        condition_id="c",
        slug=None,
        question="Will it?",
        event_id="e",
        event_title=None,
        domain="epl",
        status="active",
        trading_closed=False,
        resolution_state="unresolved",
        winning_outcome=None,
        resolved_outcome=None,
        end_date=None,
        closed_time=None,
        outcomes=(Outcome("Yes", "t1", 0.71), Outcome("No", "t2", 0.29)),
        best_bid=None,
        best_ask=None,
        spread=None,
        last_trade_price=None,
        volume_usd=None,
        liquidity_usd=None,
        tags=(),
        fetched_at="2026-09-20T12:00:00Z",
    )
    return BinaryMarket(**{**base, **fields})


# The venue's label for each prop form, as our kind and, where it says, the
# period and statistic (`sportsMarketType`, read 2026-09-23).
VENUE = {
    "totals": ("total", None),
    "first_half_totals": ("total", "1st_half"),
    "second_half_totals": ("total", "2nd_half"),
    "soccer_team_totals": ("team_total", "full"),
    "soccer_first_half_team_totals": ("team_total", "1st_half"),
    "soccer_second_half_team_totals": ("team_total", "2nd_half"),
    "spreads": ("spread", "full"),
    "first_half_spreads": ("spread", "1st_half"),
    "second_half_spreads": ("spread", "2nd_half"),
    "map_handicap": ("spread", "full"),
    "round_handicap_game_1": ("spread", "map_1"),
    "round_handicap_game_2": ("spread", "map_2"),
    "round_handicap_game_3": ("spread", "map_3"),
    "round_over_under_game_1": ("total", "map_1"),
    "round_over_under_game_2": ("total", "map_2"),
    "round_over_under_game_3": ("total", "map_3"),
    "total_corners": ("total", "full"),
    "soccer_first_half_total_corners": ("total", "1st_half"),
    "soccer_second_half_total_corners": ("total", "2nd_half"),
    "soccer_team_total_corners": ("team_total", "full"),
    "soccer_exact_score": ("exact_score", "full"),
    "soccer_first_half_exact_score": ("exact_score", "1st_half"),
    "soccer_halftime_result": ("halftime_result", None),
    "soccer_second_half_result": ("second_half_result", None),
    "both_teams_to_score": ("both_teams_to_score", "full"),
    "both_teams_to_score_first_half": ("both_teams_to_score", "1st_half"),
    "both_teams_to_score_second_half": ("both_teams_to_score", "2nd_half"),
    "soccer_anytime_goalscorer": ("anytime_scorer", None),
    "soccer_first_to_score": ("first_to_score", "full"),
    "soccer_first_half_first_to_score": ("first_to_score", "1st_half"),
    "soccer_second_half_first_to_score": ("first_to_score", "2nd_half"),
    "soccer_game_corners_odd_even": ("odd_even", "full"),
    "soccer_first_corner": ("first_corner", None),
}


def test_every_captured_prop_parses_to_the_venue_s_own_label():
    rows = json.loads(FIXTURE.read_text())["markets"]
    checked = 0
    for row in rows:
        parsed = props.parse(row["question"], row["event_title"])
        venue = row["venue_type"]
        if venue in ("moneyline", "child_moneyline"):
            assert parsed is None, row["question"]
            continue
        assert parsed is not None, row["question"]
        assert set(parsed) - {"kind"} <= set(props.PROP_KINDS[parsed["kind"]])
        assert parsed.get("team_a") and parsed.get("team_b"), row
        if venue is None:
            continue
        kind, period = VENUE[venue]
        assert parsed["kind"] == kind, row["question"]
        if period is not None:
            assert parsed["period"] == period, row["question"]
        checked += 1
    assert checked > 100


@pytest.mark.parametrize(
    ("question", "title", "expected"),
    [
        (
            "Spread: Fulham FC (-1.5)",
            "Fulham FC vs. Manchester United FC - More Markets",
            {"team": "Fulham FC", "line": "-1.5", "stat": "goals", "period": "full"},
        ),
        (
            "Fulham FC vs. Manchester United FC: Neither team to score first?",
            "Fulham FC vs. Manchester United FC - First Team to Score",
            {"team": "neither"},
        ),
        (
            "Exact Score: Fulham FC 2 - 1 Manchester United FC?",
            "Fulham FC vs. Manchester United FC - Exact Score",
            {"score": "2-1", "team_b": "Manchester United FC"},
        ),
        (
            "Games Total: O/U 2.5",
            "Counter-Strike: Peladona vs your end (BO3) - CCT South America",
            {"kind": "total", "stat": "maps", "line": "2.5", "team_a": "Peladona"},
        ),
        (
            "Map 1: Odd/Even Total Kills?",
            "Counter-Strike: A vs B (BO3) - Cup",
            {"kind": "odd_even", "stat": "kills", "period": "map_1"},
        ),
    ],
)
def test_prop_fields(question, title, expected):
    parsed = props.parse(question, title)
    assert parsed is not None
    assert expected.items() <= parsed.items()


def test_a_domain_reads_props_only_when_it_has_them_and_never_a_result_as_one():
    epl, weather = DOMAINS["epl"], DOMAINS["weather"]
    title = "Fulham FC vs. Manchester United FC"
    assert (epl.read("Will Fulham FC win on 2026-09-20?", title) or {})[
        "kind"
    ] == "match"
    assert (epl.read("Spread: Fulham FC (-1.5)", title) or {})["kind"] == "spread"
    assert weather.read("Spread: Fulham FC (-1.5)", title) is None
    assert "exact_score" in epl.all_kinds and "exact_score" not in epl.kinds
    # Found 2026-09-23: "epl " admitted Dota 2 and a cricket league.
    assert not epl.matches(
        "Games Total: O/U 2.5", "Dota 2: A vs B (BO3) - EPL Masters Group A", ()
    )


def _spec(**parts) -> Spec:
    base = {
        "name": "s",
        "selector": {"domains": ["epl"]},
        "belief": {"forecaster": "elo"},
    }
    for key, value in parts.items():
        base[key] = {**base.get(key, {}), **value} if isinstance(value, dict) else value
    return Spec.model_validate(base)


def test_the_spec_is_closed_and_bounded():
    with pytest.raises(ValidationError):
        Spec.model_validate(
            {"name": "s", "selector": {"domains": ["epl"]}, "stop_loss": 3}
        )
    with pytest.raises(ValidationError):
        _spec(sizing={"max_fraction": 2})
    with pytest.raises(ValidationError):
        _spec(selector={"domains": []})


def test_a_prompt_may_tighten_risk_and_never_loosen_it():
    assert validate(_spec(sizing={"kelly_fraction": 0.1, "max_fraction": 0.01})) == []
    problems = validate(_spec(sizing={"max_fraction": 0.1}, rule={"min_edge": 0.01}))
    assert (
        "The most staked on one market must be at most 5% of the balance." in problems
    )
    assert "The smallest edge must be at least 3 points." in problems
    workspace = Caps(max_stake_usd=50, max_open=5)
    assert validate(_spec(sizing={"max_stake_usd": 20, "max_open": 3}), workspace) == []
    assert len(validate(_spec(), workspace)) == 2  # unset is looser than a cap


def test_validation_names_what_the_markets_cannot_say():
    problems = validate(
        _spec(
            selector={
                "domains": ["epl", "chess"],
                "kinds": ["match", "corner_kicks"],
                "where": [{"field": "city", "op": "is", "values": ["Paris"]}],
            },
            belief={"forecaster": "oracle", "instructions": "be bold"},
        )
    )
    assert "There is no domain called 'chess'." in problems
    assert "The chosen domains have no markets of kind 'corner_kicks'." in problems
    assert "The chosen markets have no field 'city' to filter on." in problems
    assert "There is no forecaster called 'oracle'." in problems
    assert "Instructions and showing the price apply only to the AI model." in problems
    assert validate(_spec(belief={"forecaster": "market"}))  # never beats itself
    assert validate(
        _spec(rule={"kind": "follow", "follow": "underdog"})
    )  # has a belief
    ok = _spec(
        rule={"kind": "follow", "follow": "underdog"}, belief={"forecaster": "market"}
    )
    assert validate(ok) == []


def test_the_rendering_is_deterministic_and_says_every_setting():
    spec = _spec(
        selector={
            "kinds": ["exact_score"],
            "where": [{"field": "score", "op": "is", "values": ["0-0", "1-1"]}],
            "exclude_words": ["derby"],
            "max_spread": 0.03,
        },
        belief={
            "forecaster": "llm",
            "instructions": "draws are underpriced",
            "samples": 3,
        },
        rule={"sides": "yes", "price_max": 0.2},
        sizing={"max_stake_usd": 20, "max_per_event": 1},
        schedule={"hours_before_close": 6, "cadence_hours": 2},
    )
    text = render(spec)
    assert text == render(Spec.model_validate_json(canonical(spec)))
    whole = " ".join(text)
    for words in (
        "exact scores",
        "where score is “0-0” or “1-1”",
        "never questions mentioning “derby”",
        "In paper only, a market also needs a spread of at most 3¢",
        "claude-sonnet-5",
        "asked 3 times per market and averaged",
        "“draws are underpriced”",
        "It is not shown the market's price.",
        "only on the first outcome",
        "between 0¢ and 20¢",
        "never more than $20",
        "at most 1 in one event (in paper",
        "from 6 hours before",
        "every 2 hours",
    ):
        assert words in whole, words


def test_a_version_is_its_hash_and_a_refinement_is_a_diff():
    a = _spec()
    b = a.model_copy(
        update={"sizing": a.sizing.model_copy(update={"max_fraction": 0.02})}
    )
    assert spec_hash(a) == spec_hash(Spec.model_validate_json(canonical(a)))
    assert spec_hash(a) != spec_hash(b)
    assert diff(a, b) == [("sizing.max_fraction", 0.05, 0.02)]
    assert diff(a, a) == []


def test_the_policy_keeps_the_engine_default_and_adds_the_rule():
    fees = FeeModel()
    plain = Policy(min_edge=0.03)
    yes = plain.position(0.7, ask=0.5, bid=0.48, fees=fees)
    assert yes is not None and yes.side == "yes"
    assert Policy(sides="no").position(0.7, ask=0.5, bid=0.48, fees=fees) is None
    assert Policy(price_max=0.4).position(0.7, ask=0.5, bid=0.48, fees=fees) is None
    fav = Policy(follow="favourite", flat_fraction=0.01)
    pos = fav.position(0.0, ask=0.72, bid=0.70, fees=FeeModel(0.05))
    assert pos is not None
    assert (pos.side, pos.fraction) == ("yes", 0.01)
    assert pos.price == pytest.approx(0.72 + 0.05 * 0.72 * 0.28)
    dog = Policy(follow="underdog").position(0.0, ask=0.72, bid=0.70, fees=fees)
    assert dog is not None and dog.side == "no" and dog.price == pytest.approx(0.30)
    capped = Policy(max_stake_usd=20, max_open=2, max_per_event=1)
    assert capped.stake(0.05, 1000, 1000) == 20
    assert not capped.admits([{"event_id": "e"}], "e")
    assert capped.admits([{"event_id": "e"}], "f")
    assert not capped.admits([{}, {}], "g")


def test_the_selector_reads_fields_words_and_paper_only_floors():
    m = make_market(
        question="Will Arsenal FC win on 2026-09-20?",
        domain="epl",
        parsed={"kind": "match", "team_a": "Arsenal FC", "side": "Arsenal FC"},
        volume_usd=500.0,
    )
    base = {
        "domains": ["epl"],
        "where": [{"field": "side", "op": "is", "values": ["arsenal fc"]}],
    }
    sel = _spec(selector=base).selector
    assert run.selects(sel, live=False)(m)
    assert not run.selects(
        _spec(selector={"exclude_words": ["arsenal"]}).selector, live=False
    )(m)
    floor = _spec(selector={"min_volume_usd": 1000}).selector
    assert run.selects(floor, live=False)(m) and not run.selects(floor, live=True)(m)
    prop = replace(m, parsed={"kind": "spread", "line": "-1.5"})
    assert not run.selects(_spec().selector, live=False)(prop)  # props are opt-in
    wanted = _spec(
        selector={
            "kinds": ["spread"],
            "where": [{"field": "line", "op": "at_most", "values": ["-1"]}],
        }
    ).selector
    assert run.selects(wanted, live=False)(prop)


def test_a_strategy_trades_only_its_markets_in_its_window_within_its_caps(tmp_path):
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)

    def market(i: int, hours: float, event: str):
        return make_market(
            market_id=f"m{i}",
            condition_id=f"c{i}",
            question=f"Will Team {i} win on 2026-09-21?",
            domain="epl",
            event_id=event,
            parsed={"kind": "match", "side": f"Team {i}"},
            end_date=(now + timedelta(hours=hours)).isoformat(),
            best_bid=0.70,
            best_ask=0.72,
        )

    from vp.markets.store import write_markets

    snap = tmp_path / "snapshots" / "epl" / "s.parquet"
    write_markets(
        snap,
        [
            market(1, 5, "e1"),
            market(2, 6, "e1"),
            market(3, 30, "e2"),
            market(4, 3, "e3"),
        ],
    )
    spec = _spec(
        rule={"kind": "follow", "follow": "favourite"},
        belief={"forecaster": "market"},
        sizing={"max_per_event": 1, "max_stake_usd": 5},
    )
    ledger = Ledger(tmp_path / "ledger.jsonl")
    counts = run_cycle(
        DOMAINS["epl"],
        [run.belief(spec, "epl")],
        None,
        tmp_path,
        ledger,
        now=now,
        snapshot=snap,
        **run.paper_options(spec),
    )
    orders = [e["data"] for e in ledger.entries() if e["kind"] == "order"]
    # m3 closes in 30 h, outside the 24 h window; m2 shares m1's event.
    assert sorted(o["market_id"] for o in orders) == ["m1", "m4"]
    assert all(o["stake"] <= 5 and o["side"] == "yes" for o in orders)
    assert counts["orders"] == 2
