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
forecast. The system prompt and the tools are the same for every market, so
they are marked for prompt caching: a cache read costs a tenth of the input
price and a write a quarter more (the API's published multipliers). The
prefix must reach the model's minimum cacheable length for this to take
effect; today's is shorter, so the saving arrives with the longer domain
packs of Phase 16, and the accounting is already right when it does.

With ``batch=True`` a backtest's forecasts go through the Message Batches
API at half price, at the cost of waiting for each batch. Because the model
calls tools, one answer can take several rounds; batching is done round by
round: every conversation's next request goes into one batch, the tool
calls in the replies are answered locally, and the next round is the next
batch, until every conversation has its answer or its rounds run out.
``prefetch`` runs this for all of a backtest's markets before the backtest
asks for them one at a time.

With ``samples > 1`` the elicitation is repeated and the mean probability
is used, which averages out sampling noise at a linear cost.

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

# Multipliers on the input price for prompt-cache writes and reads, and the
# discount for batched requests (the API's published terms).
CACHE_WRITE, CACHE_READ, BATCH_DISCOUNT = 1.25, 0.10, 0.5

# Tokens one elicitation round is expected to use, for estimates before a
# run: the prompt and tool results in, the reasoning and answer out.
EXPECTED_INPUT, EXPECTED_OUTPUT, EXPECTED_ROUNDS = 1500, 600, 3

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


def estimate_usd(
    markets: int, model: str = DEFAULT_MODEL, samples: int = 1, batch: bool = False
) -> float:
    """An upper-end estimate of what forecasting `markets` markets costs."""
    price_in, price_out = PRICES[model]
    per_round = (EXPECTED_INPUT * price_in + EXPECTED_OUTPUT * price_out) / 1e6
    usd = markets * samples * EXPECTED_ROUNDS * per_round
    return usd * (BATCH_DISCOUNT if batch else 1.0)


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
    batch: bool = False
    poll_seconds: float = 30.0
    calls: list[dict[str, Any]] = field(default_factory=list)
    prefetched: dict[str, Forecast | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        if self.model not in PRICES:
            raise ValueError(f"no price recorded for model {self.model!r}")

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        key = f"{market.market_id}@{evidence.cutoff.isoformat()}"
        if key in self.prefetched:
            return self.prefetched.pop(key)
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

    def _params(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # The system prompt and the tools before it are the same for every
            # market: the stable prefix, marked for caching.
            "system": [
                {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
            ],
            "tools": TOOLS,
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            "messages": messages,
        }

    def _step(
        self,
        response: Any,
        messages: list[dict[str, Any]],
        market: BinaryMarket,
        ev: Evidence,
    ) -> tuple[float, str] | None:
        """Advance one conversation by a reply: answer its tool calls, or return
        the answer when it has one."""
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
            return None
        if response.stop_reason != "end_turn":
            raise RuntimeError(f"unexpected stop reason {response.stop_reason!r}")
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
        return float(data["probability"]), str(data["rationale"])

    def _elicit(self, market: BinaryMarket, ev: Evidence) -> tuple[float, str, float]:
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": question_block(market, ev)}
        ]
        cost = 0.0
        for _ in range(self.max_turns):
            response = self.client.messages.create(**self._params(messages))
            cost += self._record(response, market)
            answer = self._step(response, messages, market, ev)
            if answer is not None:
                return answer[0], answer[1], cost
        raise RuntimeError("tool-call rounds exhausted without an answer")

    def prefetch(self, items: list[tuple[BinaryMarket, Evidence]]) -> None:
        """Answer every (market, evidence) through the batch API, round by round.

        Does nothing unless ``batch`` is set. Answers are kept for
        :meth:`forecast` to hand back; a market whose conversation failed or
        ran out of rounds gets ``None``, as a declined market does.
        """
        if not self.batch or not items:
            return
        import time

        convs: dict[str, dict[str, Any]] = {}
        for i, (market, ev) in enumerate(items):
            for s in range(self.samples):
                convs[f"m{i}-s{s}"] = {
                    "key": f"{market.market_id}@{ev.cutoff.isoformat()}",
                    "market": market,
                    "ev": ev,
                    "messages": [
                        {"role": "user", "content": question_block(market, ev)}
                    ],
                    "cost": 0.0,
                }
        for _ in range(self.max_turns):
            open_ = {
                k: c for k, c in convs.items() if "answer" not in c and "error" not in c
            }
            if not open_:
                break
            batch = self.client.messages.batches.create(
                requests=[
                    {"custom_id": k, "params": self._params(c["messages"])}
                    for k, c in open_.items()
                ]
            )
            while batch.processing_status != "ended":
                time.sleep(self.poll_seconds)
                batch = self.client.messages.batches.retrieve(batch.id)
            for result in self.client.messages.batches.results(batch.id):
                conv = convs[result.custom_id]
                if result.result.type != "succeeded":
                    conv["error"] = result.result.type
                    continue
                response = result.result.message
                conv["cost"] += self._record(response, conv["market"], batched=True)
                try:
                    answer = self._step(
                        response, conv["messages"], conv["market"], conv["ev"]
                    )
                except Exception as exc:  # noqa: BLE001 - that market declines
                    conv["error"] = str(exc)
                    continue
                if answer is not None:
                    conv["answer"] = answer
        by_key: dict[str, list[dict[str, Any]]] = {}
        for conv in convs.values():
            by_key.setdefault(conv["key"], []).append(conv)
        for key, group in by_key.items():
            answers = [c["answer"] for c in group if "answer" in c]
            if len(answers) < len(group):
                self.prefetched[key] = None
                continue
            market, ev = group[0]["market"], group[0]["ev"]
            self.prefetched[key] = Forecast(
                market.market_id,
                self.name,
                ev.cutoff.isoformat(),
                clip(sum(a[0] for a in answers) / len(answers)),
                "\n---\n".join(a[1] for a in answers),
                cost_usd=sum(c["cost"] for c in group),
                meta={
                    "model": self.model,
                    "samples": str(self.samples),
                    "batch": "true",
                },
            )

    def _record(
        self, response: Any, market: BinaryMarket, batched: bool = False
    ) -> float:
        usage = response.usage
        price_in, price_out = PRICES[self.model]
        cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
        usd = (
            usage.input_tokens * price_in
            + cache_write * price_in * CACHE_WRITE
            + cache_read * price_in * CACHE_READ
            + usage.output_tokens * price_out
        ) / 1e6
        if batched:
            usd *= BATCH_DISCOUNT
        self.calls.append(
            {
                "market_id": market.market_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "cost_usd": usd,
                "batched": batched,
                "stop_reason": response.stop_reason,
            }
        )
        return usd
