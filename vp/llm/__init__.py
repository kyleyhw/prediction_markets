"""Models from any provider behind one call shape (docs/models.md).

``connect(provider, model, ...)`` returns a client the forecaster, the
strategy compiler and the research assistant call the same way whatever
model it reaches. This package imports nothing from the platform.
"""

from __future__ import annotations

from typing import Any

from vp.llm.providers import FREE_TIER_COUNTRIES, PROVIDERS, Provider
from vp.llm.shapes import ModelError, QuotaExhausted


class AnthropicClient:
    """The official Anthropic SDK, with the model fixed when one is given
    (none: the caller's choice, such as a strategy's tier)."""

    def __init__(self, api_key: str | None, model: str | None, max_retries: int = 6):
        import anthropic

        self._sdk = anthropic.Anthropic(api_key=api_key, max_retries=max_retries)
        self.messages = self._sdk.messages
        self.beta = self._sdk.beta
        self.model = model

    def model_for(self, requested: str) -> str:
        return self.model or requested


def connect(
    provider: str,
    model: str | None,
    key: str | None = None,
    base_url: str | None = None,
    *,
    allow_private: bool = False,
    free: bool = False,
    max_retries: int = 6,
) -> Any:
    """A client on ``provider``'s ``model``.

    Args:
        base_url: the address, for a provider without a preset one (the
            command line, for the ``command`` kind).
        allow_private: local addresses are allowed (your own copy only).
        free: the calls cost nothing (a free tier, a local model).

    Raises:
        ValueError: an unknown provider, a missing model or address, or an
            address the platform must not call.
        ModelError: the provider needs a key and none was given.
    """
    p = PROVIDERS.get(provider)
    if p is None:
        raise ValueError(f"unknown provider {provider!r}")
    if p.needs_key and not key:
        raise ModelError(
            f"{p.label} needs a key ({p.id.upper()}_API_KEY on the command line)"
        )
    if p.kind == "anthropic":
        return AnthropicClient(key, model, max_retries)
    if not model:
        raise ValueError(f"name the {p.label} model to use")
    if p.kind == "gemini":
        from vp.llm.gemini import GeminiClient

        return GeminiClient(key, model, free=free, max_retries=max_retries)
    if p.kind == "command":
        from vp.llm.command import CommandClient

        if not base_url:
            raise ValueError("give the command that runs your model program")
        return CommandClient(base_url, model)
    from vp.llm.openai_compat import OpenAICompatClient

    url = base_url or p.base_url
    if not url:
        raise ValueError("give the model's address")
    return OpenAICompatClient(
        url,
        model,
        key,
        allow_private=allow_private,
        free=free,
        max_retries=max_retries,
    )


__all__ = [
    "FREE_TIER_COUNTRIES",
    "PROVIDERS",
    "AnthropicClient",
    "ModelError",
    "Provider",
    "QuotaExhausted",
    "connect",
]
