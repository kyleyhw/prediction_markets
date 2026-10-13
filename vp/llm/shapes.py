"""The reply shape every client answers in: the subset of the Anthropic
Messages API the platform's callers read (docs/models.md).

A reply has content blocks (text, or a tool call with an id, a name and
its input), a stop reason (``end_turn``, ``tool_use``, ``max_tokens``,
``refusal``) and token usage. ``Blocks.raw`` keeps the provider's own form
of the model's turn, so the next request can send it back exactly as
received (Gemini's thought signatures, OpenAI's tool-call ids).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ModelError(RuntimeError):
    """The provider refused or failed a call; the message says why."""


class QuotaExhausted(ModelError):
    """The provider's allowance (or the platform's) is used up for now."""


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
    call_id: str | None = None  # the provider's own id for a tool call, if any


class Blocks(list):
    """A reply's blocks, with the model's turn as the provider sent it."""

    raw: Any


@dataclass
class Reply:
    content: Blocks
    stop_reason: str
    usage: Usage
    model: str


def text_of(content: Any) -> str:
    """The text of a string, or of a list of text blocks (dicts or objects)."""
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "")
        for b in content
    )


def kind_of(block: Any) -> str | None:
    return (
        block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
    )
