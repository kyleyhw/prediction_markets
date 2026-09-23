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
