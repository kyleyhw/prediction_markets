"""Portfolio risk, simultaneous Kelly, strategy health and combinatorial
positions (docs/portfolio.md, tasks 98, 99, 101 and 103)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from vp.backtest.sizing import FeeModel, kelly_fraction
from vp.portfolio import combos, exposure, health, kelly
from vp.portfolio.exposure import Position

END = datetime(2026, 9, 30, 12, tzinfo=UTC)


def _pos(market, side="yes", shares=10.0, stake=3.0, p=0.3, event=None, neg=False):
    return Position(market, event, side, shares, stake, p, "x", END, neg, "s")


def test_the_worst_case_is_exact_and_exclusive_markets_never_both_win() -> None:
    buckets = [
        _pos("a", stake=3.0, p=0.3, event="day", neg=True),
        _pos("b", stake=4.0, p=0.4, event="day", neg=True),
    ]
    # A wins: +10 - 7; B wins: +10 - 7; neither: -7.
    assert exposure.worst_case(buckets) == pytest.approx(-7.0)
    ids, won = exposure.draw(buckets, n=5_000)
    assert not (won[:, 0] & won[:, 1]).any()
    assert won[:, 0].mean() == pytest.approx(0.3, abs=0.02)
    # Both sides of one market: one of them always pays.
    hedge = [_pos("m", "yes", 10, 6, 0.6), _pos("m", "no", 10, 4, 0.6)]
    assert exposure.worst_case(hedge) == pytest.approx(0.0)
    alone = [_pos("x", stake=2.0), _pos("y", stake=5.0, event="e2")]
    assert exposure.worst_case(alone) == pytest.approx(-7.0)
    r = exposure.report(buckets + alone, bankroll=100.0)
    assert r["worst_case"] == pytest.approx(-14.0) and r["worst_case_share"] == 0.14
    assert -r["worst_case"] >= r["loss_99"] >= r["loss_95"]
    assert r["by_event"][0]["group"] == "day"


def test_every_favourite_winning_is_a_scenario() -> None:
    held = [
        _pos("a", p=0.6, event="day", neg=True, stake=6.0),
        _pos("b", p=0.3, event="day", neg=True, stake=3.0),
        _pos("c", side="no", p=0.8, stake=2.0, shares=10.0),
    ]
    # a wins its event (b loses); c's first outcome is the favourite, so "no" loses.
    assert exposure.favourites_win(held) == pytest.approx(10 - 6 - 3 - 2)


def test_simultaneous_kelly_matches_the_closed_form_and_respects_the_caps() -> None:
    R = np.array([[1 / 0.4 - 1], [-1.0]])
    f = kelly.full_kelly(R, np.array([0.6, 0.4]))
    assert f[0] == pytest.approx(kelly_fraction(0.6, 0.4), abs=1e-4)
    v = kelly._simplex(np.array([0.9, 0.8, -0.2]))
    assert v.min() >= 0 and v.sum() == pytest.approx(1.0)
    # Three buckets of one day, each cheap against the belief: per-bet sizing
    # stakes on all three, of which at most one can win.
    legs = [
        kelly.Leg(p, ask=0.2, bid=0.19, fees=FeeModel(), won_first=i == 0)
        for i, p in enumerate((0.6, 0.5, 0.45))
    ]
    out = kelly.compare_event(legs, exclusive=True)
    assert out is not None and out["positions"] == 3
    assert out["per_bet"]["total"] == pytest.approx(0.15)
    assert out["joint"]["total"] <= 0.10 + 1e-9
    assert out["per_bet_capped"]["total"] == pytest.approx(0.10)


def test_health_is_too_early_then_healthy_and_detects_decay() -> None:
    rng = np.random.default_rng(3)
    par = rng.normal(0.0, 0.05, 400)
    early = health.evaluate(par[:10])
    assert early["state"] == "too_early" and early["transitions"] == []
    assert health.evaluate(par)["state"] in ("healthy", "watch")
    worse = np.concatenate([rng.normal(0.01, 0.05, 100), rng.normal(-0.05, 0.05, 200)])
    got = health.evaluate(worse)
    assert got["state"] == "decayed"
    assert [t["to"] for t in got["transitions"]][-1] == "decayed"
    assert got["transitions"][-1]["settled"] > 100
    # An advantage that never varies is judged, not divided by zero.
    flat = health.evaluate([-0.25] * 200)
    assert flat["state"] == "decayed" and flat["cusum"] < 1e5


def test_a_conjunction_is_checked_against_its_legs() -> None:
    fine = combos.assess(0.3, [0.5, 0.6])
    assert fine["consistent"] and fine["bounds"] == pytest.approx([0.1, 0.5])
    assert fine["implied_dependence"] == pytest.approx(0.0)
    assert not combos.assess(0.55, [0.5, 0.6])["consistent"]
