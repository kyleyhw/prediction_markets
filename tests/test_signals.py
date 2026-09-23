"""The signal library: every signal passes both gates, the gates catch what
they exist to catch, a signal can be a strategy's belief, and the bench
scores signals against the market."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from vp.forecast import forecaster_names, make_forecaster
from vp.forecast.evidence import Evidence
from vp.signals import gates, registry
from vp.signals.bench import bench, verdict
from vp.strategy.spec import Spec, render, validate


@pytest.fixture(scope="module")
def roots(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[gates.Fixture, gates.Fixture]:
    return gates.fixtures(tmp_path_factory.mktemp("signals"))


@pytest.mark.parametrize("signal_id", registry.ids())
def test_every_signal_passes_purity_and_the_cutoff_sentinel(signal_id, roots) -> None:
    plain, guarded = roots
    make = lambda: registry.load(signal_id)  # noqa: E731
    assert gates.purity(make()) == []
    assert gates.cutoff_sentinel(make, plain, guarded) == []


def _module(tmp_path: Path, name: str, source: str):
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BAD = """
import os
from datetime import datetime
from dataclasses import dataclass, field
from vp.signals.base import SignalMeta

@dataclass
class Bad:
    meta: SignalMeta = field(default_factory=lambda: SignalMeta(
        id="bad", title="bad", domains=(), kinds=(), accessors=(), cutoff="",
        warmup="", references=()))

    def compute(self, market, evidence):
        open("/tmp/x")
        return datetime.now().second / 60 + len(os.environ) * 0
"""

LEAKY = """
from dataclasses import dataclass, field
from vp.signals.base import SignalMeta

@dataclass
class Leaky:
    meta: SignalMeta = field(default_factory=lambda: SignalMeta(
        id="leaky", title="leaky", domains=(), kinds=("match",), accessors=(),
        cutoff="", warmup="", references=()))

    def compute(self, market, evidence):
        # Reads the whole resolved set, past and future: what the gate is for.
        rows = evidence._resolved(market.domain)
        return sum(m.resolved_outcome or 0 for m in rows) / max(len(rows), 1)
"""


def test_the_gates_catch_an_impure_and_a_leaky_signal(tmp_path, roots) -> None:
    bad = _module(tmp_path, "vp_bad_signal", BAD).Bad()
    problems = gates.purity(bad)
    assert any("imports os" in p for p in problems)
    assert any("calls open" in p for p in problems)
    assert any("reads the clock" in p for p in problems)
    leaky = _module(tmp_path, "vp_leaky_signal", LEAKY).Leaky
    plain, guarded = roots
    assert gates.cutoff_sentinel(leaky, plain, guarded)  # its values move


def test_the_new_evidence_stops_at_the_cutoff(roots) -> None:
    plain, guarded = roots
    football = next(t.domain for t in plain.targets if t.parsed["kind"] == "total")
    a = Evidence(gates.CUTOFF, plain.root)
    b = Evidence(gates.CUTOFF, guarded.root)
    scores = a.scores(football or "")
    assert scores and scores == b.scores(football or "")
    assert all(s.settled < gates.CUTOFF for s in scores)
    assert a.settled_prices(football or "", 24) == b.settled_prices(football or "", 24)
    later = Evidence(gates.CUTOFF.replace(year=2027), guarded.root)
    assert len(later.scores(football or "")) > len(scores)
    target = next(t for t in plain.targets if t.event_id == "wtarget")
    siblings = a.event_prices(target)
    assert len(siblings) == 4 and all(m.resolved_outcome is None for m, _ in siblings)


def test_the_goals_grid_prices_a_match_consistently(roots) -> None:
    plain, _ = roots
    ev = Evidence(gates.CUTOFF, plain.root)
    signal = registry.load("poisson")
    home = next(t for t in plain.targets if t.parsed.get("side") == "Alpha FC")
    draw = next(t for t in plain.targets if t.parsed.get("side") == "draw")
    away = replace(home, parsed={**home.parsed, "side": "Delta FC"})
    total = sum(signal.compute(m, ev) or 0 for m in (home, draw, away))
    assert total == pytest.approx(1.0)
    assert (signal.compute(home, ev) or 0) > 0.5  # the stronger side, at home


def test_a_signal_is_a_belief_a_strategy_can_name(roots) -> None:
    assert "signal:dixon_coles" in forecaster_names()
    spec = Spec.model_validate(
        {
            "name": "Goals",
            "selector": {"domains": ["epl"], "kinds": ["total"]},
            "belief": {"forecaster": "signal:dixon_coles"},
        }
    )
    assert validate(spec) == []
    assert "Belief: the signal “Dixon-Coles goals”." in render(spec)
    plain, _ = roots
    target = next(t for t in plain.targets if t.parsed["kind"] == "total")
    forecast = make_forecaster("signal:dixon_coles", target.domain or "").forecast(
        target, Evidence(gates.CUTOFF, plain.root)
    )
    assert forecast is not None and forecast.forecaster == "signal:dixon_coles"


def test_the_bench_pairs_each_signal_with_the_market(tmp_path, roots) -> None:
    plain, _ = roots
    weather = next(t.domain for t in plain.targets if t.event_id == "wtarget")
    out = bench(plain.root, weather or "", max_markets=None)
    assert out["with_price"] > 200 and out["command"].startswith("vp signals bench")
    climatology = out["signals"]["climatology"]
    assert climatology["n"] > 20 and climatology["verdict"] in ("alive", "par", "anti")
    assert climatology["quarters"] and climatology["module_sha256"]
    assert verdict((0.01, 0.002, 0.02)) == "alive"
    assert verdict((-0.01, -0.02, -0.001)) == "anti"
    assert verdict((0.0, -0.01, 0.01)) == "par" and verdict(None) == "too few"


# ------------------------------------------------ blends, committees, benchmark


def test_a_blend_starts_as_the_market_and_learns_only_from_the_past(roots) -> None:
    from vp.signals.blend import Blend

    plain, guarded = roots
    target = next(t for t in plain.targets if t.event_id == "wtarget")
    few = Blend(("climatology",), min_history=10_000)
    assert few.forecast(target, Evidence(gates.CUTOFF, plain.root)) is None
    a = Blend(("climatology",), min_history=50).forecast(
        target, Evidence(gates.CUTOFF, plain.root)
    )
    b = Blend(("climatology",), min_history=50).forecast(
        target, Evidence(gates.CUTOFF, guarded.root)
    )
    assert a is not None and b is not None and a.p_hat == b.p_hat  # later rows ignored
    assert a.forecaster == "blend:climatology" and "weights" in a.rationale
    from vp.forecast import known

    assert known("blend:elo+platt_market") and not known("blend:elo+nothing")
    assert known("committee:standard") and not known("committee:nope")


def test_aggregation_rules() -> None:
    from vp.signals.committee import aggregate

    assert aggregate([0.5, 0.5]) == pytest.approx(0.5)
    assert aggregate([0.9, 0.9], rule="extremise", factor=2.0, cap=0.001) > 0.98
    assert aggregate([0.9, 0.9], rule="extremise", factor=2.0) == 0.98  # capped
    assert aggregate([0.01, 0.6, 0.62, 0.99], rule="trimmed") == pytest.approx(
        0.61, abs=0.01
    )
    assert aggregate([0.999], cap=0.02) == 0.98


def test_a_committee_asks_each_role_and_combines_them_by_its_rule(roots) -> None:
    import json
    from types import SimpleNamespace

    from vp.signals.committee import Committee

    said = {"base-rate": 0.6, "evidence analyst": 0.7, "red team": 0.5}

    class Roles:
        def __init__(self) -> None:
            self.messages = self

        def create(self, **kwargs):
            text = kwargs["messages"][0]["content"]
            p = next(v for k, v in said.items() if k in text)
            body = json.dumps({"probability": p, "rationale": f"role says {p}"})
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=body)],
                usage=SimpleNamespace(input_tokens=100, output_tokens=10),
            )

    plain, _ = roots
    target = next(t for t in plain.targets if t.parsed.get("side") == "Alpha FC")
    committee = Committee.preset("standard", client=Roles(), model="claude-sonnet-5")
    answer = committee.forecast(target, Evidence(gates.CUTOFF, plain.root))
    assert answer is not None and answer.forecaster == "committee:standard"
    assert set(k for k in answer.meta if k.endswith(".p")) == {
        "base_rate.p",
        "evidence.p",
        "red_team.p",
    }
    import math

    mean = sum(math.log(p / (1 - p)) for p in said.values()) / 3
    assert answer.p_hat == pytest.approx(1 / (1 + math.exp(-mean)))
    assert answer.cost_usd > 0 and len(committee.calls) == 3


def test_a_model_without_a_recorded_cutoff_counts_as_contaminated() -> None:
    from vp.forecast.llm import TRAINING_CUTOFFS, contaminated
    from vp.strategy.card import run_card

    assert contaminated("claude-opus-5", "2026-09-01")
    TRAINING_CUTOFFS["test-model"] = "2026-01-31"
    try:
        assert contaminated("test-model", "2026-01-15")
        assert not contaminated("test-model", "2026-02-01")
        results = {
            "common": 4,
            "candidates": 4,
            "with_price": 4,
            "settled_dates": ["2026-01-10", "2026-01-20", "2026-02-10", "2026-03-01"],
            "forecasters": [
                {"name": "market", "brier": 0.2},
                {
                    "name": "llm",
                    "brier": 0.19,
                    "log": 0.5,
                    "skill": 0.05,
                    "advantage": [0.01, 0.02, 0.05, 0.07],
                    "calibration": {"reliability": 0, "resolution": 0, "ece": 0},
                },
            ],
        }
        card = run_card(results, {"model": "test-model", "hash": "h"})
        assert card["uncontaminated_n"] == 2
        assert card["advantage_after_cutoff"]["mean"] == pytest.approx(0.025)
        unknown = run_card(results, {"model": "claude-opus-5", "hash": "h"})
        assert any("not recorded" in c for c in unknown["caveats"])
    finally:
        del TRAINING_CUTOFFS["test-model"]


def test_the_benchmark_commits_before_and_scores_after(roots) -> None:
    from datetime import timedelta

    from vp.signals import benchmark

    plain, _ = roots
    now = gates.CUTOFF - timedelta(hours=1)
    markets = [
        replace(
            t,
            outcomes=(
                replace(t.outcomes[0], implied_probability=0.4),
                t.outcomes[1],
            ),
        )
        for t in plain.targets
    ]
    week = benchmark.freeze(markets, now=now, seed=7, size=5, horizon_days=60)
    assert (
        len(week["questions"]) == 5
        and len({q["domain"] for q in week["questions"]}) == 3
    )
    again = benchmark.freeze(markets, now=now, seed=7, size=5, horizon_days=60)
    assert again["hash"] == week["hash"]  # the seed makes it reproducible
    forecasts = {q["market_id"]: 0.7 for q in week["questions"]}
    sealed = benchmark.commit(week["hash"], "signal:elo", forecasts)
    assert benchmark.verify(sealed["commitment"], sealed["salt"], sealed["payload"])
    tampered = sealed["payload"].replace("0.7", "0.8")
    assert not benchmark.verify(sealed["commitment"], sealed["salt"], tampered)
    labels = {q["market_id"]: 1 for q in week["questions"]}
    scored = benchmark.score(week, sealed["payload"], labels)
    assert scored["n"] == 5 and scored["ranked"] is False
    assert scored["brier"] == pytest.approx(0.09) and scored["skill"] > 0
