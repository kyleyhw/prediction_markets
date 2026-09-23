"""The evals harness (plan, task 59): checks over what was persisted.

Offline and deterministic: every check reads records already written (a
research turn, a backtest run's manifest and files, a compile answer) and
returns ``pass``, ``fail`` or ``not_evaluable``, which is not a pass: a
turn with no evidence call says nothing about cutoffs, and is counted
apart. The checks the plan names:

* every evidence call respected its cutoff (none in the future, and no
  date on or after the cutoff in what it returned);
* the confirmed spec is the executed spec (the version's hash, the run
  manifest's hash, and the hash of the spec file stored with the run);
* cost was reported (a model turn and a run carry their cost);
* the number gate held (re-checked from the stored text and tool results).

The compiler's cases are JSON (`tests/evals/compiler.json`): a prompt kept
exactly as written, what it should produce (a spec with given fields, a
question, a refusal), and a recorded answer that CI plays through a fake
model, so the harness itself is tested on every change. With a key the
same prompts go to the real model (`vp strategy eval --live`), which is how
the compiler's accuracy is measured (tasks 60 and 62).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from vp.strategy import gate
from vp.strategy.spec import Spec, spec_hash

PASS, FAIL, NOT_EVALUABLE = "pass", "fail", "not_evaluable"
_DAY = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""


def research_turn(words: str, content: dict[str, Any], at: datetime) -> list[Check]:
    """The checks on one stored research answer."""
    checks = []
    calls = [t for t in content.get("tools", []) if t["name"] == "evidence"]
    if not calls:
        checks.append(Check("cutoff", NOT_EVALUABLE, "no evidence call"))
    else:
        bad = []
        for call in calls:
            cutoff = date.fromisoformat(call["input"]["cutoff"])
            if cutoff > at.date():
                bad.append(f"cutoff {cutoff} after the turn")
            if call["result"].startswith("error"):
                continue
            late = [d for d in _DAY.findall(call["result"]) if d >= str(cutoff)]
            if late:
                bad.append(f"returned {late[0]} for a cutoff of {cutoff}")
        checks.append(Check("cutoff", FAIL if bad else PASS, "; ".join(bad)))
    sources = [words] + [
        t["result"]
        for t in content.get("tools", [])
        if not t["result"].startswith("error")
    ]
    text = content.get("text", "")
    if content.get("stopped"):
        checks.append(Check("number_gate", NOT_EVALUABLE, "stopped early"))
    else:
        failing = gate.check(text, sources)
        checks.append(
            Check(
                "number_gate",
                FAIL if failing else PASS,
                ", ".join(f.text for f in failing),
            )
        )
    checks.append(Check("cost_reported", PASS if "cost_usd" in content else FAIL))
    return checks


def run(
    version_hash: str, manifest: dict[str, Any] | None, spec_file: str | None
) -> list[Check]:
    """The checks on one stored strategy backtest."""
    if manifest is None or spec_file is None:
        return [Check("confirmed_is_executed", NOT_EVALUABLE, "no manifest or spec")]
    executed = spec_hash(Spec.model_validate_json(spec_file))
    hashes = [version_hash, str(manifest.get("spec_hash")), executed]
    same = len(set(hashes)) == 1
    detail = "" if same else " / ".join(h[:12] for h in hashes)
    return [Check("confirmed_is_executed", PASS if same else FAIL, detail)]


def _path(spec: dict[str, Any], dotted: str) -> Any:
    node: Any = spec
    for part in dotted.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def compile_case(case: dict[str, Any], answer: dict[str, Any]) -> list[Check]:
    """A compile answer against what its case expects."""
    expect = case["expect"]
    kind_ok = answer["kind"] == expect["kind"]
    checks = [Check("kind", PASS if kind_ok else FAIL, f"got {answer['kind']}")]
    fields = expect.get("fields", {})
    if not fields:
        return checks
    if answer.get("spec") is None:
        checks.append(
            Check("fields", NOT_EVALUABLE if not kind_ok else FAIL, "no spec")
        )
        return checks
    wrong = [
        f"{k}={_path(answer['spec'], k)!r}"
        for k, v in fields.items()
        if _path(answer["spec"], k) != v
    ]
    checks.append(Check("fields", FAIL if wrong else PASS, ", ".join(wrong)))
    return checks


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())["cases"]


def summary(results: Iterable[tuple[str, list[Check]]]) -> dict[str, Any]:
    """Counts per check and status, and the failures by case."""
    counts: Counter[tuple[str, str]] = Counter()
    failures = []
    for case, checks in results:
        for c in checks:
            counts[(c.name, c.status)] += 1
            if c.status == FAIL:
                failures.append({"case": case, **asdict(c)})
    names = sorted({n for n, _ in counts})
    return {
        "checks": {
            n: {s: counts[(n, s)] for s in (PASS, FAIL, NOT_EVALUABLE)} for n in names
        },
        "failures": failures,
    }


class Recorded:
    """A fake model that answers each prompt with its case's recorded answer,
    so CI runs the compiler and the checks without a key."""

    def __init__(self, cases: list[dict[str, Any]]) -> None:
        self.answers = {c["prompt"]: c["recorded"] for c in cases}
        self.beta = self
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        from types import SimpleNamespace

        prompt = kwargs["messages"][0]["content"]
        text = json.dumps(self.answers[prompt])
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=0, output_tokens=0),
        )


def compiler(cases: list[dict[str, Any]], client: Any) -> dict[str, Any]:
    """Every case through the compiler, checked; with the summary."""
    from vp.strategy.compiler import as_json, compile_spec

    results = []
    cost = 0.0
    for case in cases:
        out = compile_spec(case["prompt"], client=client)
        cost += out.cost_usd
        results.append((case["prompt"], compile_case(case, as_json(out))))
    passed = sum(all(c.status == PASS for c in checks) for _, checks in results)
    return summary(results) | {
        "cases": len(cases),
        "all_checks_passed": passed,
        "cost_usd": cost,
    }
