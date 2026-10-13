"""The demo model: Google's Gemini behind the Anthropic SDK's call shape.

The forecaster, the strategy compiler and the research assistant are
written against the subset of the Anthropic SDK they use:
``messages.create`` (and ``beta.messages.create``) with a system prompt,
tools, tool results and a JSON-schema answer, answered by content blocks,
a stop reason and token usage. This client takes those arguments, calls
Gemini's ``generateContent`` over REST and answers in the same shape, so
the callers run unchanged on the platform's demo model (docs/models.md).

Choices, each forced by the API (Google's documentation and the request
its official SDK sends, read 2026-10-13):

* The model's own turns go back exactly as received. Gemini 3 attaches a
  thought signature to its function calls and refuses a follow-up that
  drops it, so a reply's blocks carry the raw turn (`Blocks.raw`).
* A function call may come without an id; the client then makes one up
  for the caller and leaves it out of the function response, which Gemini
  matches by name and order.
* The key travels in the ``x-goog-api-key`` header, never the URL, so it
  is not in any request log.
* There is no batch API here (``messages.batches`` is None), so callers
  run unbatched. Thinking is left at the model's default.
* Usage: thinking tokens are billed as output; cached prompt tokens are
  counted as ordinary input, which overstates the cost slightly.

Google's official SDK is not used: it pins ``websockets`` below the
version the market-data service needs.
"""

from __future__ import annotations

import os
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx

DEMO_MODEL = "gemini-3.1-flash-lite"
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
REFUSALS = frozenset(
    {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
)


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None  # Gemini's own id for a function call, if any


class Blocks(list):
    """A reply's blocks, with the model's turn as Gemini sent it."""

    raw: dict[str, Any]


@dataclass
class Reply:
    content: Blocks
    stop_reason: str
    usage: Usage
    model: str


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "")
        for b in content
    )


def contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic-style messages as Gemini contents."""
    calls: dict[str, tuple[str, str | None]] = {}  # block id -> (name, Gemini id)
    out: list[dict[str, Any]] = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        content = m["content"]
        raw = getattr(content, "raw", None)
        if raw is not None:
            calls.update(
                {b.id: (b.name, b.call_id) for b in content if b.type == "tool_use"}
            )
            out.append(raw)
            continue
        if isinstance(content, str):
            out.append({"role": role, "parts": [{"text": content}]})
            continue
        parts: list[dict[str, Any]] = []
        for b in content:
            kind = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
            if kind == "tool_result":
                name, call_id = calls.get(b["tool_use_id"], ("unknown", None))
                answer = _text(b.get("content", ""))
                fr: dict[str, Any] = {
                    "name": name,
                    "response": {"error" if b.get("is_error") else "result": answer},
                }
                if call_id:
                    fr["id"] = call_id
                parts.append({"functionResponse": fr})
            else:
                parts.append({"text": _text([b])})
        out.append({"role": role, "parts": parts})
    return out


def request(
    messages: list[dict[str, Any]],
    max_tokens: int,
    system: Any = None,
    tools: list[dict[str, Any]] | None = None,
    output_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The generateContent body for an Anthropic-shaped call."""
    body: dict[str, Any] = {"contents": contents(messages)}
    if system:
        body["systemInstruction"] = {"parts": [{"text": _text(system)}]}
    if tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters_json_schema": t["input_schema"],
                    }
                    for t in tools
                ]
            }
        ]
    config: dict[str, Any] = {"maxOutputTokens": max_tokens}
    schema = ((output_config or {}).get("format") or {}).get("schema")
    if schema is not None:
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = schema
    body["generationConfig"] = config
    return body


def reply(data: dict[str, Any], model: str) -> Reply:
    """A generateContent answer in the Anthropic SDK's shape."""
    meta = data.get("usageMetadata") or {}
    usage = Usage(
        input_tokens=int(meta.get("promptTokenCount", 0))
        + int(meta.get("toolUsePromptTokenCount", 0)),
        output_tokens=int(meta.get("candidatesTokenCount", 0))
        + int(meta.get("thoughtsTokenCount", 0)),
    )
    blocks = Blocks()
    candidates = data.get("candidates") or []
    if not candidates:  # the prompt itself was blocked
        blocks.raw = {"role": "model", "parts": []}
        return Reply(blocks, "refusal", usage, model)
    turn = candidates[0].get("content") or {}
    parts = turn.get("parts") or []
    blocks.raw = {"role": "model", "parts": parts}
    for part in parts:
        if part.get("thought"):
            continue
        if "functionCall" in part:
            call = part["functionCall"]
            blocks.append(
                Block(
                    "tool_use",
                    id=call.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                    name=call["name"],
                    input=dict(call.get("args") or {}),
                    call_id=call.get("id"),
                )
            )
        elif "text" in part:
            if blocks and blocks[-1].type == "text":
                blocks[-1].text += part["text"]
            else:
                blocks.append(Block("text", text=part["text"]))
    finish = candidates[0].get("finishReason") or "STOP"
    if any(b.type == "tool_use" for b in blocks):
        stop = "tool_use"
    elif finish in REFUSALS:
        stop = "refusal"
    elif finish == "MAX_TOKENS":
        stop = "max_tokens"
    elif finish == "STOP":
        stop = "end_turn"
    else:
        stop = finish.lower()
    return Reply(blocks, stop, usage, model)


class Messages:
    batches = None

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        system: Any = None,
        tools: list[dict[str, Any]] | None = None,
        output_config: dict[str, Any] | None = None,
        **_ignored: Any,  # betas, fallbacks, thinking: Anthropic's own
    ) -> Reply:
        name = model if model.startswith("gemini") else self._client.model
        body = request(messages, max_tokens, system, tools, output_config)
        return reply(self._client.post(name, body), name)


class GeminiClient:
    """An ``anthropic.Anthropic``-shaped client on Gemini.

    Args:
        api_key: Google's key; ``GEMINI_API_KEY`` from the environment when
            omitted, as the Anthropic SDK reads its own.
        model: the model every call runs, whatever the caller asks for.
        http: an ``httpx.Client``; a transport-faked one in tests.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEMO_MODEL,
        http: httpx.Client | None = None,
        max_retries: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("no Gemini key: set GEMINI_API_KEY")
        self._key = key
        self.model = model
        self._http = http or httpx.Client(timeout=120.0)
        self._retries = max_retries
        self._sleep = sleep
        self.messages = Messages(self)
        self.beta = SimpleNamespace(messages=self.messages)

    def model_for(self, requested: str) -> str:
        return self.model

    def post(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._retries + 1):
            try:
                r = self._http.post(
                    API.format(model=model),
                    json=body,
                    headers={"x-goog-api-key": self._key},
                )
            except httpx.TransportError:
                if attempt == self._retries:
                    raise
            else:
                if r.status_code < 400:
                    return r.json()
                if r.status_code not in RETRY_STATUS or attempt == self._retries:
                    raise RuntimeError(
                        f"Gemini answered {r.status_code}: {r.text[:300]}"
                    )
                wait = r.headers.get("retry-after")
                if wait and wait.isdigit():
                    self._sleep(min(float(wait), 60.0))
                    continue
            self._sleep(min(2.0**attempt, 30.0) * (0.5 + random.random()))
        raise AssertionError("unreachable")
