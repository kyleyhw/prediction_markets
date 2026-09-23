"""The compiler against a fake model, the domain packs, and the preview."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_strategy import make_market
from vp.domains import DOMAINS
from vp.domains.pack import load, parse
from vp.forecast.llm import PRICES
from vp.markets.store import write_markets
from vp.strategy.compiler import SCHEMA, compile_spec
from vp.strategy.preview import bets_needed, preview
from vp.strategy.spec import Caps, Spec

GOOD = {
    "version": 1,
    "name": "Arsenal by Elo",
    "idea": "ignored: the engine keeps the person's words",
    "selector": {
        "domains": ["epl"],
        "kinds": ["match"],
        "where": [{"field": "side", "op": "is", "values": ["Arsenal FC"]}],
        "words": [],
        "exclude_words": [],
        "min_volume_usd": None,
        "min_liquidity_usd": None,
        "max_spread": None,
    },
    "belief": {
        "forecaster": "elo",
        "instructions": "",
        "tier": "standard",
        "samples": 1,
        "sees_price": False,
    },
    "rule": {
        "kind": "edge",
        "min_edge": 0.03,
        "sides": "both",
        "follow": None,
        "price_min": 0.0,
        "price_max": 1.0,
    },
    "sizing": {
        "kelly_fraction": 0.25,
        "max_fraction": 0.05,
        "flat_fraction": 0.01,
        "max_stake_usd": None,
        "max_open": None,
        "max_per_event": None,
        "initial_cash": 1000.0,
    },
    "schedule": {"hours_before_close": 24.0, "cadence_hours": 1},
}


def answer(kind: str, spec: dict | None = None, message: str = "", **extra) -> dict:
    return {
        "answer": kind,
        "message": message,
        "choices": extra.get("choices", []),
        "remember": extra.get("remember", []),
        "spec": spec,
    }


class FakeModel:
    """Plays the model: returns the queued answers in order."""

    def __init__(self, *answers: dict | str) -> None:
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        item = self.answers.pop(0)
        usage = SimpleNamespace(input_tokens=3000, output_tokens=500)
        if item == "refusal":
            return SimpleNamespace(stop_reason="refusal", content=[], usage=usage)
        blocks = [
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="text", text=json.dumps(item)),
        ]
        return SimpleNamespace(stop_reason="end_turn", content=blocks, usage=usage)


def with_(spec: dict, part: str, **values) -> dict:
    return {**spec, part: {**spec[part], **values}}


def test_a_spec_comes_back_rendered_with_the_person_s_words_and_its_cost():
    model = FakeModel(answer("spec", GOOD, "Here it is."))
    words = "Back Arsenal whenever Elo likes them more than the market"
    out = compile_spec(words, client=model, memory=["prefers small stakes"])
    assert out.kind == "spec" and out.spec is not None
    assert out.spec.idea == words  # the person's words, not the model's
    assert out.rendering[0].startswith("Markets: Premier League, match results")
    price_in, price_out = PRICES["claude-opus-5"]
    assert out.cost_usd == pytest.approx((3000 * price_in + 500 * price_out) / 1e6)
    request = model.requests[0]
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"]["format"]["schema"] == SCHEMA
    system = request["system"][0]["text"]
    assert "prefers small stakes" in system
    assert "Premier League: English football" in system  # the pack's summary
    assert request["messages"] == [{"role": "user", "content": words}]


def test_a_question_or_a_refusal_passes_through_and_nothing_is_dropped():
    q = FakeModel(answer("question", None, "Which side?", choices=["Home", "Away"]))
    out = compile_spec("Bet on the favourite in the derby", client=q)
    assert (out.kind, out.message, out.choices) == (
        "question",
        "Which side?",
        ["Home", "Away"],
    )
    r = FakeModel(
        answer("refusal", None, "A stop after three losses cannot be expressed.")
    )
    out = compile_spec("Elo on Arsenal but stop after three losses", client=r)
    assert out.kind == "refusal" and out.spec is None
    assert compile_spec("anything", client=FakeModel("refusal")).kind == "declined"


def test_the_engine_refuses_a_spec_over_the_caps_and_the_model_gets_one_repair():
    greedy = with_(GOOD, "sizing", max_fraction=0.2)
    model = FakeModel(answer("spec", greedy), answer("spec", GOOD))
    out = compile_spec("Arsenal, 20% a bet", client=model)
    assert out.kind == "spec" and out.spec is not None
    assert out.spec.sizing.max_fraction == 0.05
    repair = model.requests[1]["messages"][-1]["content"]
    assert "The most staked on one market must be at most 5% of the balance." in repair
    # Twice refused: the failures become the person's question.
    model = FakeModel(answer("spec", greedy), answer("spec", greedy))
    out = compile_spec("Arsenal, 20% a bet", client=model)
    assert out.kind == "question" and out.spec is None
    assert "at most 5% of the balance" in out.message
    # A workspace's own caps bind as the platform's do.
    model = FakeModel(answer("spec", GOOD), answer("spec", GOOD))
    out = compile_spec("x", client=model, caps=Caps(max_stake_usd=10))
    assert out.kind == "question"


def test_refining_keeps_the_idea_and_shows_the_change():
    current = Spec.model_validate({**GOOD, "idea": "Arsenal by Elo"})
    smaller = with_(GOOD, "sizing", max_fraction=0.02)
    model = FakeModel(answer("spec", smaller))
    out = compile_spec("smaller stakes", client=model, current=current)
    assert out.spec is not None and out.spec.idea == "Arsenal by Elo"
    assert out.changes == [("sizing.max_fraction", 0.05, 0.02)]
    assert current.model_dump_json() in model.requests[0]["system"][0]["text"]


def test_the_schema_is_closed_everywhere_and_carries_no_unsupported_keywords():
    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        if not isinstance(node, dict):
            return
        assert not {"minimum", "maximum", "default", "maxLength"} & node.keys()
        if "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for sub in node["properties"].values():
                walk(sub)
        for key in ("$defs",):
            for sub in node.get(key, {}).values():
                walk(sub)
        for key in ("items", "anyOf"):
            walk(node.get(key))

    walk(SCHEMA)
    assert "Spec" in SCHEMA["$defs"]


def test_every_domain_has_a_pack_that_names_its_kinds_and_is_hashed():
    for name, domain in DOMAINS.items():
        pack = load(name)
        assert pack is not None and pack.domain == name
        assert pack.sections() == [
            "Questions",
            "Fields",
            "Evidence and the cutoff",
            "Base rates",
            "Pitfalls",
        ]
        fields = pack.section("Fields") or ""
        assert all(f"`{kind}`" in fields for kind in domain.kinds), name
        assert pack.meta["sources"] and pack.meta["updated"]
    own = load("epl", "---\ndomain: epl\ntitle: Mine\n---\n## Fields\nnone\n")
    platform = load("epl")
    assert own is not None and platform is not None and own.sha256 != platform.sha256
    with pytest.raises(ValueError):
        parse("no frontmatter")


def test_the_preview_counts_what_the_selector_touches(tmp_path: Path):
    settled = datetime(2026, 5, 3, tzinfo=timezone.utc)
    resolved = [
        make_market(
            market_id=f"r{i}",
            question=f"Will Arsenal FC win on 2026-05-0{i % 9 + 1}?",
            parsed={"kind": "match", "side": "Arsenal FC" if i % 2 else "draw"},
            resolved_outcome=i % 2,
            resolution_state="resolved",
            closed_time=(settled + timedelta(days=31 * (i % 2))).isoformat(),
        )
        for i in range(6)
    ]
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", resolved)
    (tmp_path / "histories" / "epl").mkdir(parents=True)
    write_markets(tmp_path / "histories" / "epl" / "r1.parquet", [])
    write_markets(
        tmp_path / "snapshots" / "epl" / "20260920T000000Z.parquet",
        [
            make_market(
                market_id="o1",
                question="Will Arsenal FC win?",
                parsed={"kind": "match", "side": "Arsenal FC"},
            )
        ],
    )
    spec = Spec.model_validate(
        with_(
            with_(GOOD, "belief", forecaster="llm"),
            "rule",
            price_min=0.2,
            price_max=0.4,
        )
    )
    p = preview(spec, tmp_path)
    assert (p.open_now, p.resolved, p.with_history) == (1, 3, 1)
    assert p.examples == ["Will Arsenal FC win?"]
    assert p.per_month == {"2026-06": 3}
    assert p.bets_needed == bets_needed(0.03, 0.3) == round(2.8**2 * 0.21 / 0.0009)
    assert p.backtest_markets == 1 and p.backtest_usd > 0 and p.paper_month_usd > 0
    assert bets_needed(0.03) == 2178 and bets_needed(0.01) == 19600
