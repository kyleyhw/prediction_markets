"""The demo model's client (docs/models.md): Anthropic-shaped calls in,
Gemini's REST shape out and back, against a faked transport. The request
shape is the one Google's official SDK sends (captured 2026-10-13)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.test_forecast import EPL
from vp.forecast.evidence import Evidence
from vp.forecast.llm import (
    PRICES,
    LLMForecaster,
    call_cost,
    rescale,
    resolve_model,
)
from vp.llm.gemini import API, GeminiClient, reply
from vp.llm.shapes import Usage
from vp.markets.store import write_markets

KEY = "g" * 39  # pragma: allowlist secret
DEMO_MODEL = "gemini-3.1-flash-lite"
USAGE = {"promptTokenCount": 1000, "candidatesTokenCount": 80, "thoughtsTokenCount": 20}


def fake(
    answers: list[tuple[int, dict[str, Any]]], seen: list[httpx.Request]
) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = answers.pop(0)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handle))


def turn(*parts: dict[str, Any], finish: str = "STOP") -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": list(parts)}, "finishReason": finish}
        ],
        "usageMetadata": USAGE,
    }


def test_a_forecast_runs_its_tool_round_on_the_demo_model(tmp_path: Path) -> None:
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", EPL)
    ev = Evidence(datetime(2026, 3, 5, tzinfo=UTC), tmp_path)
    call = {
        "functionCall": {
            "name": "team_results",
            "args": {"team": "Arsenal FC", "limit": 5},
        },
        "thoughtSignature": "c2lnbmVk",
    }
    answer = {"text": json.dumps({"probability": 0.62, "rationale": "form"})}
    seen: list[httpx.Request] = []
    client = GeminiClient(
        KEY, DEMO_MODEL, http=fake([(200, turn(call)), (200, turn(answer))], seen)
    )
    llm = LLMForecaster(client=client, batch=True)  # asks Opus; runs the demo
    assert llm.model == DEMO_MODEL and llm.batch is False
    f = llm.forecast(EPL[4], ev)
    assert f is not None and f.p_hat == pytest.approx(0.62)
    assert f.meta["model"] == DEMO_MODEL
    price_in, price_out = PRICES[DEMO_MODEL]
    assert f.cost_usd == pytest.approx(2 * (1000 * price_in + 100 * price_out) / 1e6)

    first, second = (json.loads(r.content) for r in seen)
    assert seen[0].url == API.format(model=DEMO_MODEL)
    assert seen[0].headers["x-goog-api-key"] == KEY and KEY not in str(seen[0].url)
    assert "probability" in json.dumps(first["generationConfig"]["responseJsonSchema"])
    assert first["generationConfig"]["responseMimeType"] == "application/json"
    declared = first["tools"][0]["functionDeclarations"][0]
    assert declared["name"] == "team_results" and "parameters_json_schema" in declared
    assert (
        "careful probabilistic forecaster"
        in first["systemInstruction"]["parts"][0]["text"]
    )
    # The model's turn goes back as received, thought signature and all;
    # the answer to a call without an id names the function and no id.
    model_turn, results = second["contents"][1], second["contents"][2]
    assert model_turn == {"role": "model", "parts": [call]}
    response = results["parts"][0]["functionResponse"]
    assert response["name"] == "team_results" and "id" not in response
    assert "winner arsenal" in response["response"]["result"]


def test_ids_round_trip_and_errors_are_marked() -> None:
    seen: list[httpx.Request] = []
    call = {"functionCall": {"id": "c7", "name": "f", "args": {}}}
    client = GeminiClient(
        KEY,
        DEMO_MODEL,
        http=fake([(200, turn(call)), (200, turn({"text": "ok"}))], seen),
    )
    first = client.messages.create(
        model="claude-opus-5",
        max_tokens=100,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert first.stop_reason == "tool_use" and first.content[0].id == "c7"
    client.beta.messages.create(
        model="claude-opus-5",
        max_tokens=100,
        betas=["ignored"],
        thinking={"type": "adaptive"},
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": first.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "c7",
                        "content": "bad",
                        "is_error": True,
                    }
                ],
            },
        ],
    )
    sent = json.loads(seen[1].content)["contents"][2]["parts"][0]["functionResponse"]
    assert sent == {"name": "f", "response": {"error": "bad"}, "id": "c7"}


def test_stop_reasons_and_usage() -> None:
    text = reply(
        turn({"text": "a"}, {"text": "b"}, {"thought": True, "text": "hmm"}), "m"
    )
    assert text.stop_reason == "end_turn" and [b.text for b in text.content] == ["ab"]
    assert text.usage.input_tokens == 1000 and text.usage.output_tokens == 100
    assert reply(turn({"text": ""}, finish="SAFETY"), "m").stop_reason == "refusal"
    assert (
        reply(turn({"text": "x"}, finish="MAX_TOKENS"), "m").stop_reason == "max_tokens"
    )
    blocked = reply({"promptFeedback": {"blockReason": "SAFETY"}}, "m")
    assert blocked.stop_reason == "refusal" and blocked.content == []


def test_overload_is_retried_and_a_refusal_is_not() -> None:
    waits: list[float] = []
    seen: list[httpx.Request] = []
    answers = [(429, {}), (503, {}), (200, turn({"text": "ok"}))]
    client = GeminiClient(KEY, DEMO_MODEL, http=fake(answers, seen), sleep=waits.append)
    got = client.messages.create(
        model=DEMO_MODEL, max_tokens=10, messages=[{"role": "user", "content": "hi"}]
    )
    assert got.content[0].text == "ok" and len(waits) == 2
    client = GeminiClient(
        KEY, DEMO_MODEL, http=fake([(400, {"error": "bad schema"})], seen)
    )
    with pytest.raises(RuntimeError, match="400") as caught:
        client.messages.create(
            model=DEMO_MODEL, max_tokens=10, messages=[{"role": "user", "content": "x"}]
        )
    assert KEY not in str(caught.value)


def test_model_resolution_and_repricing(monkeypatch) -> None:
    assert resolve_model(object(), "claude-opus-5") == "claude-opus-5"
    assert resolve_model(GeminiClient(KEY, DEMO_MODEL), "claude-opus-5") == DEMO_MODEL
    # An Opus estimate at the demo model's prices: the larger ratio, output's.
    assert rescale(1.0, "claude-opus-5", DEMO_MODEL) == pytest.approx(1.5 / 25)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        LLMForecaster(model=DEMO_MODEL)
    free = GeminiClient(KEY, DEMO_MODEL, free=True)
    assert call_cost(free, Usage(1000, 1000), DEMO_MODEL) == 0.0
