"""The research assistant against a scripted model: tools over the data,
the number gate, and the loop's guards."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_forecast import root  # noqa: F401 - fixture
from vp.strategy import gate
from vp.strategy.agent import Limits, ToolBox, ToolError, research_turn

NOW = datetime(2026, 9, 23, tzinfo=UTC)
USAGE = SimpleNamespace(input_tokens=2000, output_tokens=300)


def call(name: str, **args: Any) -> Any:
    block = SimpleNamespace(type="tool_use", id=f"t-{name}", name=name, input=args)
    return SimpleNamespace(stop_reason="tool_use", content=[block], usage=USAGE)


def say(text: str) -> Any:
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=USAGE,
    )


class Script:
    """Plays the model: each reply in turn, the last one repeated."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class Counting(ToolBox):
    def __init__(self, data: Path) -> None:
        super().__init__(data, now=NOW)
        self.ran: list[str] = []

    def run(self, name: str, args: dict[str, Any]) -> str:
        self.ran.append(name)
        return super().run(name, args)


def test_an_answer_built_from_tool_results_passes_the_gate(root: Path) -> None:  # noqa: F811
    model = Script(
        call("evidence", domain="epl", subject="Arsenal FC", cutoff="2026-03-05"),
        say("Before 2026-03-05 the evidence shows Arsenal FC beat Chelsea FC."),
    )
    turn = research_turn("How has Arsenal done?", client=model, tools=Counting(root))
    assert turn.stopped is None and turn.gate["passed"] and not turn.gate["regenerated"]
    assert "Arsenal FC beat Chelsea FC" in turn.text
    # A count the model worked out itself is in no tool result.
    counted = gate.check("Arsenal FC won 1 match.", [t["result"] for t in turn.tools])
    assert [f.text for f in counted] == ["1"]
    result = turn.tools[0]["result"]
    assert "2026-03-01" in result and "2026-03-08" not in result  # the cutoff held
    request = model.requests[0]
    assert request["fallbacks"] == "default" and request["tools"][0]["strict"]
    assert turn.cost_usd > 0 and turn.input_tokens == 4000


def test_an_invented_figure_is_regenerated_once_then_replaced(root: Path) -> None:  # noqa: F811
    fixed = Script(
        call("search_markets", domain="epl", words="Arsenal", open_now=False, limit=5),
        say("Arsenal won 73% of their matches."),
        say("Here are the Arsenal markets the search found."),
    )
    turn = research_turn("Arsenal?", client=fixed, tools=Counting(root))
    assert turn.gate == {
        "passed": True,
        "regenerated": True,
        "replaced": [],
        "figures": 0,
    }
    retry = fixed.requests[2]["messages"][-1]["content"]
    assert "73%" in retry
    stubborn = Script(
        call("search_markets", domain="epl", words="Arsenal", open_now=False, limit=5),
        say("Arsenal won 73% of their matches."),
    )
    turn = research_turn("Arsenal?", client=stubborn, tools=Counting(root))
    assert turn.gate["passed"] is False and turn.gate["replaced"] == ["73%"]
    assert turn.text == f"Arsenal won {gate.POINTER} of their matches."


def test_calls_that_find_nothing_new_stop_the_turn(root: Path) -> None:  # noqa: F811
    same = call("read_pack", domain="epl", section="")
    tools = Counting(root)
    turn = research_turn(
        "tell me", client=Script(same), tools=tools, limits=Limits(model_calls=20)
    )
    assert turn.stopped == "no_progress" and "Tell me what to look at next" in turn.text
    assert len(tools.ran) == 9  # one new, then eight seen before


def test_an_identical_failing_call_is_refused_the_second_time(root: Path) -> None:  # noqa: F811
    bad = call("explain_market", domain="epl", market_id="nope")
    tools = Counting(root)
    turn = research_turn(
        "explain", client=Script(bad, bad, say("I could not find it.")), tools=tools
    )
    assert tools.ran == ["explain_market"]  # run once, refused once
    assert turn.tools[1]["result"].startswith("refused")
    assert turn.text == "I could not find it."


def test_budgets_stop_a_turn_and_a_conversation(root: Path) -> None:  # noqa: F811
    loop = call("glossary", term="brier")
    tick = iter(range(0, 10_000, 100))
    turn = research_turn(
        "x",
        client=Script(loop),
        tools=Counting(root),
        limits=Limits(seconds=250),
        clock=lambda: float(next(tick)),
    )
    assert turn.stopped == "time"
    turn = research_turn(
        "x",
        client=Script(loop),
        tools=Counting(root),
        limits=Limits(model_calls=3, no_progress=99),
    )
    assert turn.stopped == "calls"
    spent = research_turn("x", client=Script(loop), tools=Counting(root), used_turns=40)
    assert spent.stopped == "session" and spent.cost_usd == 0
    cancelled = []

    def progress(fraction: float, message: str) -> None:
        cancelled.append(message)
        raise KeyboardInterrupt  # a job's cancellation raises in progress

    with pytest.raises(KeyboardInterrupt):
        research_turn("x", client=Script(loop), tools=Counting(root), progress=progress)
    assert cancelled == ["thinking ($0.000 so far)"]


def test_the_tools_read_the_data_and_refuse_the_future(root: Path) -> None:  # noqa: F811
    tools = ToolBox(root, now=NOW)
    with pytest.raises(ToolError, match="future"):
        tools.run(
            "evidence",
            {"domain": "epl", "subject": "Arsenal FC", "cutoff": "2027-01-01"},
        )
    highs = tools.run(
        "evidence", {"domain": "weather", "subject": "London", "cutoff": "2025-03-05"}
    )
    assert "2025-03-04" in highs and "2025-03-05" not in highs
    assert "Brier score:" in tools.run("glossary", {"term": "brier"})
    assert "sections: Questions" in tools.run(
        "read_pack", {"domain": "epl", "section": ""}
    )
    assert "problems" in tools.run(
        "preview_spec", {"spec_json": '{"name": "x", "selector": {"domains": ["epl"]}}'}
    )
    explained = tools.run("explain_market", {"domain": "epl", "market_id": "5"})
    assert "resolution rules: not recorded" in explained


@pytest.mark.parametrize(
    ("text", "sources", "failing"),
    [
        ("61% and 62¢ and 2,178 bets", ["0.614 0.62 2178"], []),
        ("-0.29% over 39 bets", ["-0.0029 39"], []),
        ("claude-opus-5 on map_1, run 4ee13a8", [""], []),
        ("1. first\n2. second", [""], []),
        ("about 45% of 7 markets", ["0.614"], ["45%", "7"]),
        ("$12 in fees", ["11.2"], ["$12"]),
        ("$11 in fees", ["11.2"], []),
    ],
)
def test_the_gate_reads_figures_as_a_person_would(text, sources, failing) -> None:
    assert [f.text for f in gate.check(text, sources)] == failing
