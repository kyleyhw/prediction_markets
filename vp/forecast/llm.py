"""The LLM forecaster: a language model elicited for a probability.

The model is given the market question, the domain's structured fields, and
the information cutoff, and it may call tools that return cutoff-bounded
evidence (recent results of each team, the head-to-head record, realised
temperatures at the station). It must answer with a probability and a
rationale in a fixed JSON shape, enforced by the API's structured output.
The market price is deliberately *not* shown: a model that can see $q$ tends
to return $q$, and the question is whether it has information the price
does not.

Every call is logged with its token usage, and the cost is computed from a
price table per million tokens so the backtest can report dollars per
forecast. With ``samples > 1`` the elicitation is repeated and the mean
probability is used, which averages out sampling noise at a linear cost.

The model is called through the official SDK; the client is injectable so
the elicitation loop is tested offline against a fake, and a run without
credentials fails at construction rather than mid-backtest.

Known failure modes, observed in Vibe-Trading and expected here: the model
anchoring on round numbers (0.5, 0.7); overconfidence on famous teams;
stating facts from its training data that post-date the cutoff (the prompt
forbids it, the tools cannot enforce it, and the leakage check in Phase 10
is the measurement of how much this happens).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from vp.forecast.base import Forecast, clip
from vp.forecast.evidence import Evidence, canonical
from vp.markets.schema import BinaryMarket

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"

# USD per million tokens, input and output, for cost accounting.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

SYSTEM = """You are a careful probabilistic forecaster of binary prediction-market
contracts.

You are given a market question and an information cutoff. Reason only from
information available before the cutoff: the evidence returned by the tools,
and general knowledge that was public before the cutoff. Do not use anything
you may know about what happened after it. If you are unsure whether you know
something from after the cutoff, do not use it.

Call the tools to gather evidence before answering. Then give the probability
that the FIRST-NAMED outcome occurs, as a number in (0, 1), with a short
rationale that states the evidence you relied on. Avoid round-number anchors;
report the probability you actually hold."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "probability": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["probability", "rationale"],
    "additionalProperties": False,
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "team_results",
        "description": (
            "Recent settled match results of a team in the market's domain, "
            "newest first, all before the cutoff."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["team", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "head_to_head",
        "description": "Settled matches between two teams before the cutoff.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"team_a": {"type": "string"}, "team_b": {"type": "string"}},
            "required": ["team_a", "team_b"],
            "additionalProperties": False,
        },
    },
    {
        "name": "daily_highs",
        "description": (
            "Realised daily maximum temperatures at a city before the cutoff, "
            "newest first, each known to the bucket that resolved."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["city", "limit"],
            "additionalProperties": False,
        },
    },
]


def run_tool(
    name: str, args: dict[str, Any], market: BinaryMarket, ev: Evidence
) -> str:
    """Execute one evidence tool; every read goes through the cutoff-bounded object."""
    domain = market.domain or ""
    if name == "team_results":
        team = canonical(str(args["team"]))
        rows = [r for r in ev.results(domain) if team in (r.team_a, r.team_b)]
        return _lines(
            f"{r.settled.date()}: {r.team_a} vs {r.team_b}, winner {r.winner}"
            for r in reversed(rows[-int(args["limit"]) :])
        )
    if name == "head_to_head":
        pair = {canonical(str(args["team_a"])), canonical(str(args["team_b"]))}
        rows = [r for r in ev.results(domain) if {r.team_a, r.team_b} == pair]
        return _lines(
            f"{r.settled.date()}: {r.team_a} vs {r.team_b}, winner {r.winner}"
            for r in reversed(rows)
        )
    if name == "daily_highs":
        obs = ev.daily_highs(str(args["city"]))
        return _lines(
            f"{o.day}: high in [{o.low if o.low is not None else '-inf'}, "
            f"{o.high if o.high is not None else 'inf'}] {o.unit}"
            for o in reversed(obs[-int(args["limit"]) :])
        )
    return f"unknown tool {name}"


def _lines(items: Any) -> str:
    text = "\n".join(items)
    return text or "no records before the cutoff"


def question_block(market: BinaryMarket, ev: Evidence) -> str:
    """The user turn: question, outcomes, parsed fields and the cutoff."""
    first, second = market.outcomes
    fields = "\n".join(f"  {k}: {v}" for k, v in sorted(market.parsed.items()))
    return (
        f"Information cutoff: {ev.cutoff.isoformat()}\n"
        f"Domain: {market.domain}\n"
        f"Event: {market.event_title}\n"
        f"Question: {market.question}\n"
        f"Outcomes: first = {first.name!r}, second = {second.name!r}\n"
        f"Market end date: {market.end_date}\n"
        f"Structured fields:\n{fields or '  (none)'}\n\n"
        "What is the probability that the first outcome occurs?"
    )


@dataclass
class LLMForecaster:
    """Elicit a probability from a Claude model with tool access to evidence.

    Args:
        model: Model id; priced from :data:`PRICES`.
        client: An ``anthropic.Anthropic``-compatible client. Created from
            the environment when omitted.
        samples: Independent elicitations averaged per market.
        max_turns: Cap on tool-call rounds per elicitation.
        effort: ``output_config.effort`` passed to the model.
    """

    model: str = DEFAULT_MODEL
    client: Any = None
    samples: int = 1
    max_turns: int = 6
    effort: str = "medium"
    max_tokens: int = 4000
    name: str = "llm"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        if self.model not in PRICES:
            raise ValueError(f"no price recorded for model {self.model!r}")

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        probabilities: list[float] = []
        rationales: list[str] = []
        cost = 0.0
        for _ in range(self.samples):
            try:
                p, rationale, usd = self._elicit(market, evidence)
            except Exception as exc:  # noqa: BLE001 - one failed market must not end a run
                logger.warning("llm forecast failed for %s: %s", market.market_id, exc)
                return None
            probabilities.append(p)
            rationales.append(rationale)
            cost += usd
        p_hat = sum(probabilities) / len(probabilities)
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(p_hat),
            "\n---\n".join(rationales),
            cost_usd=cost,
            meta={"model": self.model, "samples": str(self.samples)},
        )

    def _elicit(self, market: BinaryMarket, ev: Evidence) -> tuple[float, str, float]:
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": question_block(market, ev)}
        ]
        cost = 0.0
        for _ in range(self.max_turns):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM,
                tools=TOOLS,
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
                },
                messages=messages,
            )
            cost += self._record(response, market)
            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                results = [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": run_tool(block.name, dict(block.input), market, ev),
                    }
                    for block in response.content
                    if block.type == "tool_use"
                ]
                messages.append({"role": "user", "content": results})
                continue
            if response.stop_reason != "end_turn":
                raise RuntimeError(f"unexpected stop reason {response.stop_reason!r}")
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
            return float(data["probability"]), str(data["rationale"]), cost
        raise RuntimeError("tool-call rounds exhausted without an answer")

    def _record(self, response: Any, market: BinaryMarket) -> float:
        usage = response.usage
        price_in, price_out = PRICES[self.model]
        usd = (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1e6
        self.calls.append(
            {
                "market_id": market.market_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": usd,
                "stop_reason": response.stop_reason,
            }
        )
        return usd
