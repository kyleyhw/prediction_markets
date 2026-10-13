"""Any model behind one call shape (docs/models.md): the OpenAI-compatible
client against a faked server, a program as the model, the presets,
`connect`, and the address check that keeps a typed address from reaching
the platform's own network."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.test_forecast import EPL
from vp.forecast.evidence import Evidence
from vp.forecast.llm import LLMForecaster, call_cost, client_for_model
from vp.llm import FREE_TIER_COUNTRIES, PROVIDERS, ModelError, connect
from vp.llm.command import CommandClient
from vp.llm.openai_compat import OpenAICompatClient, check_address
from vp.markets.store import write_markets

SCHEMA = {
    "type": "object",
    "properties": {"probability": {"type": "number"}, "rationale": {"type": "string"}},
    "required": ["probability", "rationale"],
    "additionalProperties": False,
}


def server(answers: list[tuple[int, dict[str, Any]]], seen: list[dict]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(
            {"headers": dict(request.headers), "body": json.loads(request.content)}
        )
        status, body = answers.pop(0)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handle))


def chat(message: dict[str, Any], finish: str = "stop") -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", **message}, "finish_reason": finish}
        ],
        "usage": {"prompt_tokens": 900, "completion_tokens": 60},
    }


def test_a_forecast_runs_on_an_openai_compatible_model(tmp_path: Path) -> None:
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", EPL)
    ev = Evidence(datetime(2026, 3, 5, tzinfo=UTC), tmp_path)
    call = {
        "id": "c1",
        "type": "function",
        "function": {
            "name": "team_results",
            "arguments": json.dumps({"team": "Arsenal FC", "limit": 5}),
        },
    }
    answer = json.dumps({"probability": 0.58, "rationale": "form"})
    seen: list[dict] = []
    http = server(
        [
            (200, chat({"content": None, "tool_calls": [call]}, "tool_calls")),
            (200, chat({"content": answer})),
        ],
        seen,
    )
    client = OpenAICompatClient(
        "https://api.groq.com/openai/v1", "llama-x", "k" * 30, http=http
    )
    f = LLMForecaster(client=client).forecast(EPL[4], ev)
    assert f is not None and f.p_hat == pytest.approx(0.58)
    assert f.meta["model"] == "llama-x" and f.cost_usd == 0, "unpriced: own bill"
    first, second = (s["body"] for s in seen)
    assert seen[0]["headers"]["authorization"] == "Bearer " + "k" * 30
    assert first["model"] == "llama-x" and first["tool_choice"] == "auto"
    assert first["messages"][0]["role"] == "system"
    assert first["tools"][0]["function"]["name"] == "team_results"
    assert first["response_format"]["type"] == "json_schema"
    # The model's turn goes back with its call ids, an empty content (not
    # null), and one tool message answers it.
    assistant, tool = second["messages"][2], second["messages"][3]
    assert assistant["tool_calls"][0]["id"] == "c1" and assistant["content"] == ""
    assert tool["role"] == "tool" and tool["tool_call_id"] == "c1"
    assert "winner arsenal" in tool["content"]


def test_refusals_of_known_differences_are_repaired_once_and_remembered() -> None:
    seen: list[dict] = []
    answers = [
        (
            400,
            {"error": "Unsupported parameter: 'max_tokens', use max_completion_tokens"},
        ),
        (500, {"error": "response_format: Input should be 'text' or 'json_object'"}),
        (200, chat({"content": '{"probability": 0.5, "rationale": "x"}'})),
        (200, chat({"content": "{}"})),
    ]
    client = OpenAICompatClient(
        "https://api.openai.com/v1", "m", "k" * 30, http=server(answers, seen)
    )
    ask: dict[str, Any] = {
        "model": "m",
        "max_tokens": 50,
        "system": "sys",
        "messages": [{"role": "user", "content": "hi"}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }
    got = client.messages.create(**ask)
    assert got.stop_reason == "end_turn" and "probability" in got.content[0].text
    last = seen[2]["body"]
    assert "max_completion_tokens" in last and "max_tokens" not in last
    assert last["response_format"] == {"type": "json_object", "schema": SCHEMA}
    assert "JSON schema" in last["messages"][0]["content"]
    client.messages.create(**ask)  # remembered: one request, already adapted
    assert len(seen) == 4 and seen[3]["body"]["response_format"]["schema"] == SCHEMA


def test_errors_say_what_went_wrong_without_the_key() -> None:
    for status, words in ((401, "refused the key"), (404, "no model"), (400, "400")):
        client = OpenAICompatClient(
            "https://api.openai.com/v1",
            "m",
            "secret-" + "x" * 30,
            http=server([(status, {"error": "nope"})], []),
        )
        with pytest.raises(ModelError, match=words) as caught:
            client.messages.create(
                model="m", max_tokens=5, messages=[{"role": "user", "content": "x"}]
            )
        assert "secret-" not in str(caught.value)


def test_a_typed_address_must_be_public_https() -> None:
    check_address("https://8.8.8.8/v1")
    for bad in (
        "http://8.8.8.8/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.5/v1",
        "https://169.254.169.254/latest",
        "https://[::1]/v1",
        "https://[::ffff:10.0.0.1]/v1",
        "file:///etc/passwd",
    ):
        with pytest.raises(ValueError):
            check_address(bad)
    check_address("http://localhost:11434/v1", allow_private=True)  # your own copy


def test_a_program_of_your_own_is_the_model(tmp_path: Path) -> None:
    program = tmp_path / "model.py"
    program.write_text(
        "import json, sys\n"
        "req = json.load(sys.stdin)\n"
        "last = req['messages'][-1]['content']\n"
        "if isinstance(last, str):\n"
        "    out = {'content': [{'type': 'tool_use', 'id': 't1', 'name': "
        "'league_table', 'input': {}}]}\n"
        "else:\n"
        "    out = {'content': [{'type': 'text', 'text': json.dumps("
        "{'probability': 0.4, 'rationale': req['system'][:5]})}], "
        "'usage': {'input_tokens': 3, 'output_tokens': 4}}\n"
        "print(json.dumps(out))\n"
    )
    client = CommandClient(f"{sys.executable} {program}", model="rules")
    first = client.messages.create(
        model="x",
        max_tokens=9,
        system="hello",
        messages=[{"role": "user", "content": "q"}],
    )
    assert first.stop_reason == "tool_use" and first.content[0].name == "league_table"
    second = client.messages.create(
        model="x",
        max_tokens=9,
        system="hello",
        messages=[
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": first.content},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "t"}
                ],
            },
        ],
    )
    assert json.loads(second.content[0].text)["rationale"] == "hello"
    assert call_cost(client, second.usage, "rules") == 0.0
    broken = CommandClient(f"{sys.executable} -c 'import sys; sys.exit(3)'")
    with pytest.raises(ModelError, match="exited 3"):
        broken.messages.create(
            model="x", max_tokens=1, messages=[{"role": "user", "content": "q"}]
        )


def test_presets_connect_and_the_free_tier_rule() -> None:
    assert {"anthropic", "gemini", "openai", "groq", "ollama", "custom"} <= set(
        PROVIDERS
    )
    for p in PROVIDERS.values():
        assert p.base_url is None or p.base_url.startswith(
            ("https://", "http://localhost")
        )
    groq = connect("groq", "llama-x", "k" * 30)
    assert groq.url == "https://api.groq.com/openai/v1/chat/completions"
    assert groq.model_for("claude-opus-5") == "llama-x"
    with pytest.raises(ModelError, match="needs a key"):
        connect("openai", "m")
    with pytest.raises(ValueError, match="address"):
        connect("custom", "m")
    with pytest.raises(ValueError):
        connect("ollama", "qwen")  # a local address, outside your own copy
    assert connect("ollama", "qwen", allow_private=True, free=True).free
    with pytest.raises(ValueError, match="unknown provider"):
        connect("nope", "m")
    # The demo's countries: Google's list, without the EEA, CH and the UK.
    assert {"US", "IN", "BR", "JP", "KE"} <= FREE_TIER_COUNTRIES
    assert not {"DE", "FR", "NL", "IE", "NO", "IS", "LI", "CH", "GB", "JE"} & (
        FREE_TIER_COUNTRIES
    )
    assert not {"CN", "RU", "IR", "KP", "CU"} & FREE_TIER_COUNTRIES, "not offered"


def test_the_command_line_picks_any_provider(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "g" * 30)
    client, model = client_for_model("groq:llama-3.3-70b")
    assert model == "llama-3.3-70b" and client.model == model
    client, model = client_for_model("ollama:qwen2.5:1.5b")
    assert model == "qwen2.5:1.5b" and client.free


def test_the_example_program_forecasts_a_match(tmp_path: Path) -> None:
    """`examples/my_model.py`, the guide's own-script model, runs as is."""
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", EPL)
    ev = Evidence(datetime(2026, 3, 5, tzinfo=UTC), tmp_path)
    example = Path(__file__).resolve().parent.parent / "examples" / "my_model.py"
    client = connect("command", "my-model", base_url=f"{sys.executable} {example}")
    f = LLMForecaster(client=client).forecast(EPL[4], ev)
    # "Will Chelsea FC win?": Chelsea lost its one recent match, to Arsenal.
    assert f is not None and f.p_hat == pytest.approx(1 / 3, abs=1e-3)
    assert f.meta["model"] == "my-model" and f.cost_usd == 0
