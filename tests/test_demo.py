"""The static demo (docs/demo.md): its export, and its JavaScript engine
against the Python engine it ports, on the same inputs."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.test_strategy import make_market
from vp import demo
from vp.domains import DOMAINS
from vp.markets.store import write_history, write_markets
from vp.strategy import run
from vp.strategy.spec import Spec, render, validate

NODE = shutil.which("node")
ENGINE = (Path(__file__).resolve().parent.parent / "pages" / "engine.js").as_uri()
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def js(call: str, payload: Any) -> Any:
    """Run ``call`` (an expression over ``engine`` and ``input``) in node."""
    script = (
        f"import * as engine from {json.dumps(ENGINE)};"
        "let raw='';process.stdin.on('data',d=>raw+=d);"
        "process.stdin.on('end',()=>{const input=JSON.parse(raw);"
        f"process.stdout.write(JSON.stringify({call}));}});"
    )
    assert NODE is not None
    done = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _dataset(root: Path, n: int = 80, seed: int = 3) -> None:
    """Resolved matches with hourly prices, some with fees, a few props."""
    rng = random.Random(seed)
    markets, words = [], ["derby", "cup", "final", "league"]
    for i in range(n):
        settled = START + timedelta(days=i, hours=rng.randint(0, 20))
        kind = "match" if i % 9 else "total"
        side = f"Team {i % 7}"
        markets.append(
            make_market(
                market_id=str(i),
                condition_id=f"c{i}",
                question=f"Will {side} win the {rng.choice(words)} on day {i}?",
                event_id=f"e{i // 2}",
                domain="epl",
                status="closed",
                trading_closed=True,
                resolution_state="resolved",
                resolved_outcome=rng.randint(0, 1),
                closed_time=settled.isoformat(),
                parsed={
                    "kind": kind,
                    "team_a": side,
                    "team_b": f"Team {(i + 3) % 7}",
                    "side": side,
                },
                fee_rate=None if i % 4 == 0 else rng.choice([0.03, 0.05]),
            )
        )
        points = [
            {
                "timestamp": (settled - timedelta(hours=h)).isoformat(),
                "implied_probability": round(rng.uniform(0.04, 0.96), 3),
            }
            for h in (200, 100, 50, 30, 10, 3, 2)
        ]
        write_history(
            root / "histories" / "epl" / f"{i}.parquet",
            market_id=str(i),
            clob_token_id=f"t{i}",
            outcome="Yes",
            points=points,
            bar_minutes=60,
        )
    write_markets(root / "markets" / "epl" / "resolved.parquet", markets)


SPECS: list[dict[str, Any]] = [
    {"belief": {"forecaster": "constant"}},
    {
        "belief": {"forecaster": "constant"},
        "rule": {"min_edge": 0.05, "sides": "no", "price_max": 0.8},
        "sizing": {"max_fraction": 0.02, "max_stake_usd": 15},
    },
    {
        "belief": {"forecaster": "market"},
        "rule": {"kind": "follow", "follow": "underdog", "price_min": 0.1},
        "schedule": {"hours_before_close": 6},
    },
    {
        "belief": {"forecaster": "market"},
        "rule": {"kind": "follow", "follow": "favourite"},
        "selector": {"domains": ["epl"], "words": ["derby", "cup"]},
        "schedule": {"hours_before_close": 72},
    },
    {
        "belief": {"forecaster": "elo"},
        "selector": {
            "domains": ["epl"],
            "where": [{"field": "side", "op": "is_not", "values": ["team 1"]}],
            "exclude_words": ["final"],
        },
    },
    {
        "belief": {"forecaster": "constant"},
        "selector": {"domains": ["epl"], "kinds": ["total"]},
        "schedule": {"hours_before_close": 1},
    },
]


def _spec(parts: dict[str, Any]) -> Spec:
    return Spec.model_validate(
        {"name": "s", "selector": {"domains": ["epl"]}} | parts | {"idea": "x"}
    )


@needs_node
@pytest.mark.parametrize("parts", SPECS)
def test_the_page_backtests_exactly_as_the_engine_does(tmp_path, parts):
    _dataset(tmp_path)
    spec = _spec(parts)
    data = demo.export_domain(tmp_path, "epl", names=["constant", "elo"])
    ctx = demo.context(["epl"])
    expected = run.backtest(spec, tmp_path, tmp_path / "out")["epl"]
    belief = expected.results[-1]
    got = js(
        "engine.backtest(input.spec, input.data, input.ctx)",
        {"spec": spec.model_dump(mode="json"), "data": data, "ctx": ctx},
    )
    assert got["scored"] == expected.common
    assert len(got["bets"]) == len(belief.bets)
    for mine, theirs in zip(got["bets"], belief.bets, strict=True):
        assert mine["market"]["id"] == theirs.market_id
        assert mine["side"] == theirs.side
        assert mine["stake"] == pytest.approx(theirs.stake, abs=1e-9)
        assert mine["pnl"] == pytest.approx(theirs.pnl, abs=1e-9)
        assert mine["fee"] == pytest.approx(theirs.fee, abs=1e-9)
    if spec.rule.kind == "edge":
        assert got["brier"] == pytest.approx(belief.brier, abs=1e-9)
        assert got["skill"] == pytest.approx(belief.skill, abs=1e-9)


def test_the_export_holds_only_what_was_known_at_each_cutoff(tmp_path):
    _dataset(tmp_path, n=12)
    data = demo.export_domain(tmp_path, "epl", names=["constant"])
    first = data["markets"][0]
    # Prices are read before each cutoff: 1 h before settling the last
    # point is the one 2 h before; 168 h before, the one 200 h before.
    assert set(first["price"]) == {str(h) for h in demo.CUTOFFS}
    assert first["f"]["constant"]["24"] == 0.5
    assert [m["settled"] for m in data["markets"]] == sorted(
        m["settled"] for m in data["markets"]
    )


def _all_domains_specs() -> list[dict[str, Any]]:
    rng = random.Random(7)
    beliefs = ["market", "constant", "elo", "climatology", "llm", "signal:poisson"]
    out = []
    for i in range(60):
        domain = rng.choice([*DOMAINS, "chess"])
        kinds = rng.choice(
            [[], ["match"], ["total"], ["daily_temperature"], ["corner_kicks"]]
        )
        out.append(
            {
                "name": f"s{i}",
                "selector": {
                    "domains": [domain],
                    "kinds": kinds,
                    "where": rng.choice(
                        [
                            [],
                            [{"field": "side", "op": "is", "values": ["Arsenal FC"]}],
                            [{"field": "city", "op": "contains", "values": ["Lo"]}],
                            [{"field": "low", "op": "at_least", "values": ["x"]}],
                        ]
                    ),
                    "words": rng.choice([[], ["cup"], ["a", "b's", "c"]]),
                    "min_volume_usd": rng.choice([None, 1000, 2500.5]),
                    "max_spread": rng.choice([None, 0.05]),
                },
                "belief": {
                    "forecaster": rng.choice(beliefs),
                    "instructions": rng.choice(["", "be careful"]),
                },
                "rule": rng.choice(
                    [
                        {},
                        {"kind": "follow", "follow": "favourite"},
                        {"kind": "follow"},
                        {"min_edge": 0.01, "sides": "yes"},
                        {"price_min": 0.2, "price_max": 0.15},
                        {"price_min": 0.05, "price_max": 0.9, "sides": "no"},
                    ]
                ),
                "sizing": rng.choice(
                    [
                        {},
                        {"kelly_fraction": 0.5, "max_fraction": 0.1},
                        {"flat_fraction": 0.005, "max_stake_usd": 12.5, "max_open": 3},
                        {"initial_cash": 2500.75, "max_per_event": 1},
                    ]
                ),
                "schedule": rng.choice(
                    [{}, {"hours_before_close": 6, "cadence_hours": 4}]
                ),
            }
        )
    return out


@needs_node
def test_the_page_checks_and_words_a_spec_as_the_engine_does():
    ctx = demo.context(DOMAINS)
    cases = _all_domains_specs() + [
        {"name": "s", "selector": {"domains": ["epl"]}, "stop_loss": 3},
        {"name": "s", "selector": {"domains": []}},
        {"name": "", "selector": {"domains": ["epl"]}},
        {"name": "s", "selector": {"domains": ["epl"]}, "sizing": {"max_fraction": 2}},
        {"name": "s", "selector": {"domains": ["epl"]}, "rule": {"sides": "maybe"}},
    ]
    got = js(
        "input.cases.map(c => { const [spec, errors] = engine.conform(c, input.ctx.spec_schema);"
        " return errors.length ? {errors} : {spec, problems: engine.validate(spec, input.ctx),"
        " words: engine.render(spec, input.ctx)}; })",
        {"cases": cases, "ctx": ctx},
    )
    for case, mine in zip(cases, got, strict=True):
        try:
            spec = Spec.model_validate(case)
        except ValidationError:
            assert mine.get("errors"), case
            continue
        assert mine.get("spec") == spec.model_dump(mode="json"), case
        assert mine["problems"] == validate(spec, forecasters=ctx["beliefs"]), case
        if spec.belief.forecaster != "llm":
            assert mine["words"] == render(spec), case


def test_the_context_is_the_compiler_s_own():
    from vp.strategy import compiler

    ctx = demo.context(DOMAINS)
    assert ctx["system"].startswith(compiler.SYSTEM)
    assert "$ref" not in json.dumps(ctx["schema"])
    assert "llm" not in ctx["beliefs"] and "market" in ctx["beliefs"]
    assert all(p["kind"] != "command" for p in ctx["providers"])


def test_a_script_is_the_belief_and_answers_only_in_range(tmp_path, monkeypatch):
    from vp.cli import main
    from vp.forecast import Evidence
    from vp.strategy.script import ScriptForecaster

    _dataset(tmp_path)
    script = tmp_path / "mine.py"
    script.write_text(
        "def forecast(market, evidence):\n"
        "    if market.parsed.get('kind') != 'match':\n"
        "        return None\n"
        "    return 0.7, 'always 70%'\n"
    )
    spec = tmp_path / "s.json"
    spec.write_text(_spec({"belief": {"forecaster": "market"}}).model_dump_json())
    out = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "vp",
            "strategy",
            "backtest",
            str(spec),
            "--root",
            str(tmp_path),
            "--out",
            str(out),
            "--script",
            str(script),
        ],
    )
    main()
    rows = [json.loads(line) for line in (out / "epl" / "forecasts.jsonl").open()]
    mine = [r for r in rows if r["forecaster"] == "script:mine"]
    assert mine and {r["p_hat"] for r in mine} == {0.7}
    assert {r["rationale"] for r in mine} == {"always 70%"}

    script.write_text("def forecast(market, evidence):\n    return 1.5\n")
    with pytest.raises(ValueError, match="between 0 and 1"):
        ScriptForecaster(script).forecast(make_market(), Evidence(START, tmp_path))
