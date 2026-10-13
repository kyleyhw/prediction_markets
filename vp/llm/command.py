"""A program of your own as the model (docs/models.md, "Your own copy").

The program is run once per call. It reads the request as one JSON object
on its standard input::

    {"model": ..., "system": "...", "messages": [...], "tools": [...],
     "schema": {...} or null, "max_tokens": 4000}

where each message is ``{"role": "user" | "assistant", "content": ...}``
and content is a string or a list of blocks (``text``, ``tool_use``,
``tool_result``) in the Anthropic Messages API's form. It writes the reply
as one JSON object on its standard output::

    {"content": [{"type": "text", "text": "..."}
                 | {"type": "tool_use", "id": "...", "name": "...", "input": {}}],
     "stop_reason": "end_turn" | "tool_use" | "max_tokens" | "refusal",
     "usage": {"input_tokens": 0, "output_tokens": 0}}

Anything can stand behind it: a rule of thumb, a local model, a call to a
service. `examples/my_model.py` is a working one. This kind is set only by
whoever runs a copy, in its environment; the hosted platform never runs a
command a person typed.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from types import SimpleNamespace
from typing import Any

from vp.llm.shapes import Block, Blocks, ModelError, Reply, Usage, text_of


def _plain(value: Any) -> Any:
    """Messages as JSON: the reply blocks this module made become dicts."""
    if isinstance(value, Block):
        if value.type == "tool_use":
            return {
                "type": "tool_use",
                "id": value.id,
                "name": value.name,
                "input": value.input,
            }
        return {"type": value.type, "text": value.text}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


class Messages:
    batches = None

    def __init__(self, client: CommandClient) -> None:
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
        **_ignored: Any,
    ) -> Reply:
        c = self._client
        request = {
            "model": c.model,
            "system": text_of(system or ""),
            "messages": _plain(messages),
            "tools": tools or [],
            "schema": ((output_config or {}).get("format") or {}).get("schema"),
            "max_tokens": max_tokens,
        }
        try:
            done = subprocess.run(
                c.command,
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=c.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ModelError(f"your model program did not run: {exc}") from None
        if done.returncode != 0:
            raise ModelError(
                f"your model program exited {done.returncode}: {done.stderr[-300:]}"
            )
        try:
            data = json.loads(done.stdout)
        except json.JSONDecodeError:
            raise ModelError(
                "your model program did not print one JSON object"
            ) from None
        blocks = Blocks(
            Block(
                b.get("type", "text"),
                text=b.get("text", ""),
                id=b.get("id", ""),
                name=b.get("name", ""),
                input=dict(b.get("input") or {}),
            )
            for b in data.get("content") or []
        )
        blocks.raw = data.get("content") or []
        usage = data.get("usage") or {}
        return Reply(
            blocks,
            data.get("stop_reason")
            or (
                "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
            ),
            Usage(
                int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
            ),
            c.model,
        )


class CommandClient:
    """A client that runs ``command`` for each call (see the module's text)."""

    free = True

    def __init__(self, command: str, model: str = "my-model", timeout: float = 600.0):
        self.command = shlex.split(command)
        if not self.command:
            raise ModelError("no command given for your model program")
        self.model = model
        self.timeout = timeout
        self.messages = Messages(self)
        self.beta = SimpleNamespace(messages=self.messages)

    def model_for(self, requested: str) -> str:
        return self.model
