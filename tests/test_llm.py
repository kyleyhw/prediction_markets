"""The LLM forecaster's elicitation loop against a fake client.

The fake plays the model: it first calls two evidence tools, then answers in
the structured JSON shape. The test checks that tool calls are routed through
the cutoff-bounded evidence, that the loop appends results correctly, that
cost is computed from usage at the recorded prices, and that samples are
averaged.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_forecast import EPL, ROUND_ONE, epl_match
from vp.forecast.evidence import Evidence
from vp.forecast.llm import PRICES, LLMForecaster, run_tool
from vp.markets.store import write_markets


class FakeMessages:
    def __init__(self, answers: list[float]) -> None:
        self.answers = answers
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        usage = SimpleNamespace(input_tokens=1000, output_tokens=100)
        last = kwargs["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], str):
            # First turn: ask for evidence on both teams.
            blocks = [
                SimpleNamespace(
                    type="tool_use",
                    id="t1",
                    name="team_results",
                    input={"team": "Arsenal FC", "limit": 5},
                ),
                SimpleNamespace(
                    type="tool_use",
                    id="t2",
                    name="head_to_head",
                    input={"team_a": "Arsenal FC", "team_b": "Chelsea FC"},
                ),
            ]
            return SimpleNamespace(stop_reason="tool_use", content=blocks, usage=usage)
        # Second turn: the tool results arrived; answer.
        results = {r["tool_use_id"]: r["content"] for r in last["content"]}
        assert "winner arsenal" in results["t1"] and "winner arsenal" in results["t2"]
        assert "2026-03-08" not in results["t1"], "round two is after the cutoff"
        p = self.answers.pop(0)
        text = json.dumps({"probability": p, "rationale": f"evidence says {p}"})
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=usage,
        )


def test_llm_loop_routes_tools_through_evidence(tmp_path: Path) -> None:
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", EPL)
    ev = Evidence(datetime(2026, 3, 5, tzinfo=timezone.utc), tmp_path)
    fake = FakeMessages([0.6, 0.7])
    llm = LLMForecaster(client=SimpleNamespace(messages=fake), samples=2)
    f = llm.forecast(EPL[4], ev)
    assert f is not None and f.p_hat == pytest.approx(0.65) and f.forecaster == "llm"
    assert f.rationale == "evidence says 0.6\n---\nevidence says 0.7"
    # Two samples, two turns each, 1000 in and 100 out tokens per turn.
    price_in, price_out = PRICES["claude-opus-5"]
    assert f.cost_usd == 4 * (1000 * price_in + 100 * price_out) / 1e6
    assert len(llm.calls) == 4
    first = fake.requests[0]
    assert (
        first["model"] == "claude-opus-5"
        and first["tools"][0]["name"] == "team_results"
    )
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert "Information cutoff: 2026-03-05" in first["messages"][0]["content"]
    assert "0.45" not in first["messages"][0]["content"], (
        "the market price is never shown"
    )


def test_run_tool_unknown_and_empty(tmp_path: Path) -> None:
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", EPL)
    ev = Evidence(datetime(2026, 3, 5, tzinfo=timezone.utc), tmp_path)
    m = epl_match("x", "Spurs", "Wolves", "Spurs", 1, ROUND_ONE)
    assert (
        run_tool("team_results", {"team": "Spurs", "limit": 3}, m, ev)
        == "no records before the cutoff"
    )
    assert run_tool("nope", {}, m, ev).startswith("unknown tool")


def test_llm_failure_declines(tmp_path: Path) -> None:
    class Broken:
        def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    ev = Evidence(datetime(2026, 3, 5, tzinfo=timezone.utc), tmp_path)
    llm = LLMForecaster(client=SimpleNamespace(messages=Broken()))
    assert llm.forecast(EPL[4], ev) is None


class FakeBatches:
    """The Message Batches API over the same fake model: each batch's
    requests are answered by `FakeMessages.create`, one round per batch."""

    def __init__(self, model: FakeMessages) -> None:
        self.model = model
        self.created: list[list[dict[str, Any]]] = []
        self._results: dict[str, list[Any]] = {}

    def create(self, *, requests: list[dict[str, Any]]) -> Any:
        self.created.append(requests)
        batch_id = f"b{len(self.created)}"
        self._results[batch_id] = [
            SimpleNamespace(
                custom_id=r["custom_id"],
                result=SimpleNamespace(
                    type="succeeded", message=self.model.create(**r["params"])
                ),
            )
            for r in requests
        ]
        return SimpleNamespace(id=batch_id, processing_status="in_progress")

    def retrieve(self, batch_id: str) -> Any:
        return SimpleNamespace(id=batch_id, processing_status="ended")

    def results(self, batch_id: str) -> list[Any]:
        return self._results[batch_id]


def test_batch_mode_answers_round_by_round_at_half_price(tmp_path: Path) -> None:
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", EPL)
    ev = Evidence(datetime(2026, 3, 5, tzinfo=timezone.utc), tmp_path)
    fake = FakeMessages([0.6, 0.7])
    batches = FakeBatches(fake)
    client = SimpleNamespace(
        messages=SimpleNamespace(create=fake.create, batches=batches)
    )
    llm = LLMForecaster(client=client, samples=2, batch=True, poll_seconds=0)
    llm.prefetch([(EPL[4], ev)])
    # Round one asks both samples for evidence in one batch; round two answers.
    assert [len(b) for b in batches.created] == [2, 2]
    f = llm.forecast(EPL[4], ev)
    assert (
        f is not None and f.p_hat == pytest.approx(0.65) and f.meta["batch"] == "true"
    )
    price_in, price_out = PRICES["claude-opus-5"]
    assert f.cost_usd == pytest.approx(
        0.5 * 4 * (1000 * price_in + 100 * price_out) / 1e6
    )
    # The answer is handed out once; a second ask would elicit afresh.
    assert llm.prefetched == {}


def test_cache_reads_and_writes_are_priced_and_the_prefix_marked(
    tmp_path: Path,
) -> None:
    from vp.forecast.llm import CACHE_READ, CACHE_WRITE, estimate_usd

    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", EPL)
    ev = Evidence(datetime(2026, 3, 5, tzinfo=timezone.utc), tmp_path)
    fake = FakeMessages([0.6])
    original = fake.create

    def with_cache(**kwargs: Any) -> Any:
        response = original(**kwargs)
        response.usage.cache_read_input_tokens = 2000
        response.usage.cache_creation_input_tokens = 500
        return response

    llm = LLMForecaster(
        client=SimpleNamespace(messages=SimpleNamespace(create=with_cache))
    )
    f = llm.forecast(EPL[4], ev)
    assert f is not None
    assert fake.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    price_in, price_out = PRICES["claude-opus-5"]
    per_turn = (
        1000 * price_in
        + 500 * price_in * CACHE_WRITE
        + 2000 * price_in * CACHE_READ
        + 100 * price_out
    ) / 1e6
    assert f.cost_usd == pytest.approx(2 * per_turn)
    assert llm.calls[0]["cache_read_tokens"] == 2000
    assert estimate_usd(10, batch=True) == pytest.approx(estimate_usd(10) / 2)
    assert estimate_usd(0) == 0
