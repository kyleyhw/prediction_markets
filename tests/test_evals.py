"""The evals harness: each check can pass, fail, or not apply, and the
compiler's held-out prompts run in CI against their recorded answers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from vp.strategy import evals
from vp.strategy.spec import Spec, canonical, spec_hash

CASES = Path(__file__).parent / "evals" / "compiler.json"
AT = datetime(2026, 9, 23, tzinfo=UTC)


def evidence(cutoff: str, result: str) -> dict:
    return {"name": "evidence", "input": {"cutoff": cutoff}, "result": result}


def statuses(checks: list[evals.Check]) -> dict[str, str]:
    return {c.name: c.status for c in checks}


def test_research_answers_are_checked_for_cutoffs_figures_and_cost() -> None:
    good = {
        "text": "Arsenal FC beat Chelsea FC on 2026-03-01.",
        "tools": [evidence("2026-03-05", "2026-03-01: Arsenal FC vs Chelsea FC")],
        "cost_usd": 0.02,
    }
    assert statuses(evals.research_turn("q", good, AT)) == {
        "cutoff": "pass",
        "number_gate": "pass",
        "cost_reported": "pass",
    }
    leaked = good | {"tools": [evidence("2026-03-05", "2026-03-08: a later result")]}
    assert statuses(evals.research_turn("q", leaked, AT))["cutoff"] == "fail"
    future = good | {"tools": [evidence("2027-01-01", "error: in the future")]}
    assert statuses(evals.research_turn("q", future, AT))["cutoff"] == "fail"
    invented = good | {"text": "Arsenal won 7 of 9."}
    assert statuses(evals.research_turn("q", invented, AT))["number_gate"] == "fail"
    said = good | {"text": "You asked about 7 of 9."}
    assert statuses(evals.research_turn("7 of 9?", said, AT))["number_gate"] == "pass"
    quiet = {"text": "Nothing to add.", "tools": []}
    got = statuses(evals.research_turn("q", quiet, AT))
    assert got["cutoff"] == "not_evaluable" and got["cost_reported"] == "fail"
    stopped = quiet | {"stopped": "no_progress", "cost_usd": 0.1}
    assert statuses(evals.research_turn("q", stopped, AT))["number_gate"] == (
        "not_evaluable"
    )


def test_the_confirmed_spec_must_be_the_one_that_ran() -> None:
    spec = Spec.model_validate({"name": "s", "selector": {"domains": ["epl"]}})
    digest = spec_hash(spec)
    manifest = {"spec_hash": digest}
    assert statuses(evals.run(digest, manifest, canonical(spec))) == {
        "confirmed_is_executed": "pass"
    }
    other = spec.model_copy(update={"name": "t"})
    assert evals.run(digest, manifest, canonical(other))[0].status == "fail"
    assert evals.run(digest, None, None)[0].status == "not_evaluable"


def test_the_held_out_prompts_run_through_the_compiler_in_ci() -> None:
    cases = evals.load_cases(CASES)
    prompts = [c["prompt"] for c in cases]
    assert len(prompts) == len(set(prompts)) >= 24
    assert {c["expect"]["kind"] for c in cases} == {"spec", "question", "refusal"}
    out = evals.compiler(cases, evals.Recorded(cases))
    assert out["failures"] == [] and out["all_checks_passed"] == len(cases)
    # A wrong answer is caught: the harness is not a rubber stamp.
    wrong = [dict(cases[0], recorded=cases[1]["recorded"])]
    caught = evals.compiler(wrong, evals.Recorded(wrong))
    assert caught["checks"]["fields"]["fail"] == 1
