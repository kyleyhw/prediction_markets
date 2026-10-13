"""Any OpenAI-compatible server behind the platform's one call shape.

Chat Completions is the API most providers and every common self-hosted
server speak (OpenAI, OpenRouter, Groq, Mistral, DeepSeek, Together, xAI,
Ollama, LM Studio, llama.cpp, vLLM), so one adapter plugs all of them in
(docs/models.md). The callers' Anthropic-shaped requests become chat
messages: the system prompt a ``system`` message, tools ``function``
tools, a tool result one ``tool`` message per call, and a JSON-schema
answer ``response_format``. Replies come back as content blocks
(`vp/llm/shapes.py`).

Servers differ, so known refusals are repaired once and remembered for
the client's life: a server that rejects ``json_schema`` is asked for
``json_object`` holding the schema (llama.cpp's servers constrain the
output to it), then for bare ``json_object``, with the schema stated in
the system prompt either way; one that rejects ``max_tokens`` (OpenAI's
newer models) gets ``max_completion_tokens``.

An address a person typed is the one way they could aim the platform's
servers at something; :func:`check_address` refuses anything but a public
``https`` address unless private ones are allowed (your own copy).
Redirects are not followed.
"""

from __future__ import annotations

import ipaddress
import json
import random
import socket
import time
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import httpx

from vp.llm.shapes import (
    Block,
    Blocks,
    ModelError,
    QuotaExhausted,
    Reply,
    Usage,
    kind_of,
    text_of,
)

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
SCHEMA_NOTE = (
    "\n\nAnswer with one JSON object, and nothing else, that follows this "
    "JSON schema:\n"
)


def check_address(url: str, allow_private: bool = False) -> None:
    """Refuse an address the platform must not call (ValueError)."""
    parts = urlsplit(url)
    if parts.scheme != "https" and not (allow_private and parts.scheme == "http"):
        raise ValueError("the address must start with https://")
    host = parts.hostname
    if not host:
        raise ValueError("the address has no host name")
    if allow_private:
        return
    try:
        found = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(f"{host} could not be found") from None
    for info in found:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if not (mapped or ip).is_global:
            raise ValueError(f"{host} is not a public address")


def chat_messages(system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic-style messages as Chat Completions messages."""
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": text_of(system)})
    for m in messages:
        content = m["content"]
        raw = getattr(content, "raw", None)
        if raw is not None:
            out.append(raw)
            continue
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        texts = []
        for b in content:
            if kind_of(b) == "tool_result":
                answer = text_of(b.get("content", ""))
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": b["tool_use_id"],
                        "content": f"error: {answer}" if b.get("is_error") else answer,
                    }
                )
            else:
                texts.append(text_of([b]))
        if texts:
            out.append({"role": m["role"], "content": "".join(texts)})
    return out


def reply(data: dict[str, Any], model: str) -> Reply:
    """A Chat Completions answer in the platform's shape."""
    meta = data.get("usage") or {}
    usage = Usage(
        input_tokens=int(meta.get("prompt_tokens") or 0),
        output_tokens=int(meta.get("completion_tokens") or 0),
    )
    choices = data.get("choices") or []
    blocks = Blocks()
    if not choices:
        blocks.raw = {"role": "assistant", "content": ""}
        return Reply(blocks, "refusal", usage, model)
    choice = choices[0]
    message = choice.get("message") or {}
    text = text_of(message.get("content") or "")
    calls = message.get("tool_calls") or []
    for call in calls:
        call["id"] = call.get("id") or f"call_{uuid.uuid4().hex[:12]}"
    # An empty string, not null: some servers refuse a null content beside
    # tool calls (llama.cpp's Python server, 2026-10-13); OpenAI takes both.
    raw: dict[str, Any] = {"role": "assistant", "content": text}
    if calls:
        raw["tool_calls"] = calls
    blocks.raw = raw
    if text:
        blocks.append(Block("text", text=text))
    for call in calls:
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            raise ModelError(
                f"the model's call to {fn.get('name')} is not JSON"
            ) from None
        blocks.append(
            Block("tool_use", id=call["id"], name=fn.get("name", ""), input=dict(args))
        )
    finish = choice.get("finish_reason") or "stop"
    if calls:
        stop = "tool_use"
    elif message.get("refusal") or finish == "content_filter":
        stop = "refusal"
    elif finish == "length":
        stop = "max_tokens"
    else:
        stop = "end_turn"
    return Reply(blocks, stop, usage, model)


class Messages:
    batches = None

    def __init__(self, client: OpenAICompatClient) -> None:
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
        c = self._client
        schema = ((output_config or {}).get("format") or {}).get("schema")
        if schema is not None and c.json_mode != "schema":
            system = text_of(system or "") + SCHEMA_NOTE + json.dumps(schema)
        body: dict[str, Any] = {
            "model": c.model,
            "messages": chat_messages(system, messages),
            c.tokens_field: max_tokens,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
            # OpenAI's default, said out loud: some servers (llama.cpp's
            # Python server) ignore tools unless asked (2026-10-13).
            body["tool_choice"] = "auto"
        if schema is not None:
            body["response_format"] = {
                "schema": {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": schema, "strict": True},
                },
                "object_schema": {"type": "json_object", "schema": schema},
                "object": {"type": "json_object"},
            }[c.json_mode]
        return reply(c.post(body), c.model)


class OpenAICompatClient:
    """A client on any Chat Completions server, in the platform's shape.

    Args:
        base_url: the server's address up to ``/v1`` (the presets know it).
        model: the model every call runs, whatever the caller asks for.
        api_key: sent as a bearer token; a local server may need none.
        allow_private: allow loopback and private addresses (your own copy).
        free: the calls cost nothing (a free tier, a model on your computer).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        *,
        allow_private: bool = False,
        free: bool = False,
        http: httpx.Client | None = None,
        max_retries: int = 6,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 600.0,
    ) -> None:
        check_address(base_url, allow_private)
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.free = free
        self._key = api_key
        self._allow_private = allow_private
        self._http = http or httpx.Client(timeout=timeout, follow_redirects=False)
        self._retries = max_retries
        self._sleep = sleep
        # How this server takes a JSON-schema answer: "schema" (OpenAI's
        # json_schema), "object_schema" (json_object holding the schema, as
        # llama.cpp's servers do), or "object" (bare json_object).
        self.json_mode = "schema"
        self.tokens_field = "max_tokens"
        self.messages = Messages(self)
        self.beta = SimpleNamespace(messages=self.messages)

    def model_for(self, requested: str) -> str:
        return self.model

    def _repair(self, body: dict[str, Any], error: str) -> bool:
        """Adapt a request a server refused for a known difference; False if
        the refusal is not one of them."""
        low = error.lower()
        if "max_completion_tokens" in low and self.tokens_field == "max_tokens":
            self.tokens_field = "max_completion_tokens"
            body["max_completion_tokens"] = body.pop("max_tokens")
            return True
        fmt = body.get("response_format") or {}
        if "response_format" in low or "json_schema" in low or "schema" in low:
            if fmt.get("type") == "json_schema":
                # llama.cpp's servers take the schema inside json_object and
                # hold the output to it (unconstrained JSON can run on as
                # whitespace to the token limit: 2026-10-13).
                self.json_mode = "object_schema"
                schema = fmt["json_schema"]["schema"]
                body["response_format"] = {"type": "json_object", "schema": schema}
                note = SCHEMA_NOTE + json.dumps(schema)
                if body["messages"] and body["messages"][0]["role"] == "system":
                    body["messages"][0]["content"] += note
                else:
                    body["messages"].insert(0, {"role": "system", "content": note})
                return True
            if fmt.get("type") == "json_object" and "schema" in fmt:
                self.json_mode = "object"
                del fmt["schema"]
                return True
        return False

    def post(self, body: dict[str, Any]) -> dict[str, Any]:
        check_address(self.url, self._allow_private)  # names can be re-pointed
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        repaired = 0
        attempt = 0
        while True:
            try:
                r = self._http.post(self.url, json=body, headers=headers)
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    raise ModelError(
                        f"could not reach the model's address: {exc}"
                    ) from None
            else:
                if r.status_code < 300:
                    return r.json()
                # Validation refusals come as 400, 422 or (llama.cpp) 500.
                if (
                    r.status_code in (400, 422, 500)
                    and repaired < 3
                    and self._repair(body, r.text)
                ):
                    repaired += 1
                    continue
                if r.status_code in (401, 403):
                    raise ModelError(f"the provider refused the key ({r.status_code})")
                if r.status_code == 404:
                    raise ModelError(
                        f"the provider has no model {self.model!r} at this address"
                    )
                if r.status_code == 429 and attempt >= self._retries:
                    raise QuotaExhausted("the provider's quota is used up for now")
                if r.status_code not in RETRY_STATUS or attempt >= self._retries:
                    raise ModelError(
                        f"the provider answered {r.status_code}: {r.text[:300]}"
                    )
                wait = r.headers.get("retry-after")
                if wait and wait.isdigit():
                    self._sleep(min(float(wait), 60.0))
                    attempt += 1
                    continue
            self._sleep(min(2.0**attempt, 30.0) * (0.5 + random.random()))
            attempt += 1
