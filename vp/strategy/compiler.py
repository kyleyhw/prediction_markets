"""The compiler: a person's words to a strategy spec (plan, task 52).

One structured-output call to a Claude model answers with exactly one of a
complete ``spec``, a clarifying ``question`` (with choices when there are
few), or a ``refusal`` naming the part of the request the spec cannot say,
so a constraint is never dropped (docs/strategies.md). A spec is then
checked by the engine (:func:`vp.strategy.spec.validate`, caps included);
if it fails, the model is told why once and may repair it or ask the
person, and if it still fails the failures become the question the person
sees. The model is never shown a price or a result: compiling is
translation, not forecasting. What the person confirms is
:func:`~vp.strategy.spec.render` of the spec, never the model's prose.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from vp.domains import DOMAINS, Domain
from vp.domains.pack import load as load_pack
from vp.forecast.llm import usage_usd
from vp.strategy.spec import (
    FORECASTER_NAMES_PLAIN,
    KIND_NAMES,
    Caps,
    Spec,
    diff,
    render,
    validate,
)

logger = logging.getLogger(__name__)

#: The compiler's model: a person reads and confirms what it produces, so
#: the strongest general model is used (docs/strategies.md, model tiers).
COMPILER_MODEL = "claude-opus-5"
#: Server-side refusal fallback (the "default" form and its beta header).
FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: One repair round after the engine refuses a spec.
REPAIRS = 1


class Answer(BaseModel):
    """The model's structured answer."""

    model_config = ConfigDict(extra="forbid")

    answer: Literal["spec", "question", "refusal"]
    message: str
    choices: list[str]
    remember: list[str]
    spec: Spec | None


# Keywords the structured-output grammar does not take; bounds are checked
# by the engine after the answer arrives, as every other rule is.
_UNSUPPORTED = {
    "default",
    "title",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
}


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED:
            continue
        if key in ("properties", "$defs"):
            out[key] = {name: _strict(sub) for name, sub in value.items()}
        else:
            out[key] = _strict(value)
    if "properties" in out:
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    return out


#: The answer's JSON schema as sent: every object closed, every field
#: required (the defaults are in the prompt), no numeric bounds.
SCHEMA: dict[str, Any] = _strict(Answer.model_json_schema())

SYSTEM = """You translate a person's description of a forecasting strategy for
binary prediction-market contracts into a strategy spec: JSON that the engine
runs exactly as written. You are a translator, not a forecaster: never judge
whether the strategy is good, never estimate a probability, never add a
condition the person did not ask for.

Answer with exactly one of:
- "spec": the complete spec. Keep every default below unless the person's
  words set it. Put the person's first description, verbatim, in "idea",
  and give the strategy a short plain "name".
- "question": one short question when something essential is ambiguous
  (which domain, which side, which markets), with "choices" when there are
  two to five natural answers. Ask only what changes the spec.
- "refusal": the request needs something the spec cannot express (for
  example a stop after losses, conditions on news or weather forecasts,
  times of day, martingale sizing, markets outside the domains listed). Say
  in "message" exactly which part cannot be expressed and what the spec can
  do instead. Never drop a condition silently; if one part of a request can
  be expressed and another cannot, refuse and say so.

"message" is always written for the person, in plain words, without figures
that are not in their request or in this prompt. "remember" lists at most
two short durable preferences the person stated about themselves (risk
appetite, interests, sizing), to be offered to them for saving; usually it is
empty.

Rules of the spec:
- selector.domains: from the domains below. selector.kinds: from that domain's
  kinds; empty means its main markets (not props). selector.where filters
  parsed fields (op is, is_not, contains take any of "values"; at_least and
  at_most take one number as a string). Field values are as the venue writes
  them (team names with their suffix, for example "Arsenal FC").
- belief.forecaster: one of the forecasters below. instructions, tier,
  samples and sees_price apply only to "llm"; sees_price is true only if the
  person explicitly asks for the model to see the market price.
- rule.kind "edge" trades when the belief beats the price after fees by
  min_edge; "follow" makes no forecast (belief.forecaster must be "market")
  and buys the favourite or the underdog, at a flat stake, inside the price
  band. An "edge" rule needs a belief other than "market".
- Prices, bands and edges are probabilities between 0 and 1 (10 cents is
  0.10; 3 points of edge is 0.03). Fractions of the balance are between 0
  and 1 (5% is 0.05).
- Risk may be lowered freely but never raised above the caps below. If the
  person asks for more, ask whether the cap will do, as a question.
- schedule.hours_before_close is when trading starts before a market ends and
  when a backtest forecasts; cadence_hours is how often paper trading checks.
"""


def _context(
    domains: Mapping[str, Domain],
    forecasters: Iterable[str],
    caps: Caps,
    memory: Sequence[str],
    current: Spec | None,
    packs: Mapping[str, str],
) -> str:
    parts = ["Domains (from each domain's pack; ask for more only if needed):"]
    for name, domain in domains.items():
        pack = load_pack(name, packs.get(name))
        parts.append(f"\n## {name}: {pack.summary if pack else domain.summary}")
        kinds = ", ".join(
            f"{k} ({KIND_NAMES.get(k, k)}; fields {', '.join(f)})"
            for k, f in domain.all_kinds.items()
        )
        parts.append(f"kinds: {kinds}")
        fields = pack.section("Fields") if pack else None
        if fields:
            parts.append(fields)
    parts.append("\nForecasters:")
    parts += [f"- {n}: {FORECASTER_NAMES_PLAIN.get(n, n)}" for n in forecasters]
    parts.append(
        "\nDefaults: "
        + Spec.model_validate(
            {"name": "x", "selector": {"domains": ["x"]}}
        ).model_dump_json(exclude={"name", "idea", "selector"})
        + ' and selector {"kinds": [], "where": [], "words": [], "exclude_words":'
        ' [], "min_volume_usd": null, "min_liquidity_usd": null, "max_spread": null}'
    )
    parts.append(
        f"\nCaps: kelly_fraction at most {caps.kelly_fraction}, max_fraction at most"
        f" {caps.max_fraction}, flat_fraction at most {caps.flat_fraction}, min_edge"
        f" at least {caps.min_edge}"
        + "".join(
            f", {name} at most {value}"
            for name, value in (
                ("max_stake_usd", caps.max_stake_usd),
                ("max_open", caps.max_open),
                ("max_per_event", caps.max_per_event),
            )
            if value is not None
        )
        + "."
    )
    if memory:
        parts.append(
            "\nWhat the person has asked to be remembered (context only; the"
            " spec follows their words in this conversation):"
        )
        parts += [f"- {m}" for m in memory]
    if current is not None:
        parts.append(
            "\nThe person is refining this confirmed spec. Answer with the whole"
            " new spec, changing only what they ask for:\n" + current.model_dump_json()
        )
    return "\n".join(parts)


@dataclass
class Compiled:
    """What the compiler produced for one message."""

    kind: Literal["spec", "question", "refusal", "declined"]
    message: str
    choices: list[str] = field(default_factory=list)
    remember: list[str] = field(default_factory=list)
    spec: Spec | None = None
    rendering: list[str] = field(default_factory=list)
    changes: list[tuple[str, Any, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = COMPILER_MODEL
    input_tokens: int = 0
    output_tokens: int = 0


def compile_spec(
    words: str,
    *,
    client: Any,
    history: Sequence[tuple[str, str]] = (),
    current: Spec | None = None,
    memory: Sequence[str] = (),
    caps: Caps = Caps(),
    domains: Mapping[str, Domain] = DOMAINS,
    forecasters: Iterable[str] | None = None,
    packs: Mapping[str, str] | None = None,
    model: str = COMPILER_MODEL,
) -> Compiled:
    """Compile one message of a person's conversation into a spec.

    ``history`` holds the conversation's earlier turns as ``(role, text)``;
    ``current`` is the confirmed spec being refined, if any; ``packs`` are
    a workspace's own pack texts by domain.
    """
    if forecasters is None:
        from vp.forecast import FORECASTER_NAMES

        forecasters = FORECASTER_NAMES
    names = list(forecasters)
    system = (
        SYSTEM + "\n" + _context(domains, names, caps, memory, current, packs or {})
    )
    messages: list[dict[str, Any]] = [
        {"role": role, "content": text} for role, text in history
    ]
    messages.append({"role": "user", "content": words})
    cost = 0.0
    tokens = [0, 0]
    problems: list[str] = []
    for attempt in range(REPAIRS + 1):
        response = client.beta.messages.create(
            model=model,
            max_tokens=8000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            system=[
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=messages,
        )
        cost += usage_usd(response.usage, model)
        tokens[0] += response.usage.input_tokens
        tokens[1] += response.usage.output_tokens
        if response.stop_reason == "refusal":
            return Compiled(
                "declined",
                "The model declined to translate this request.",
                cost_usd=cost,
                model=model,
                input_tokens=tokens[0],
                output_tokens=tokens[1],
            )
        text = next(b.text for b in response.content if b.type == "text")
        try:
            answer = Answer.model_validate_json(text)
        except ValidationError as exc:
            problems = [
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            ]
            answer = None
        if answer is not None and answer.answer != "spec":
            return Compiled(
                answer.answer,
                answer.message,
                answer.choices,
                answer.remember,
                cost_usd=cost,
                model=model,
                input_tokens=tokens[0],
                output_tokens=tokens[1],
            )
        if answer is not None and answer.spec is not None:
            spec = answer.spec.model_copy(
                update={"idea": current.idea if current else words}
            )
            problems = validate(spec, caps, domains=domains, forecasters=names)
            if not problems:
                return Compiled(
                    "spec",
                    answer.message,
                    remember=answer.remember,
                    spec=spec,
                    rendering=render(spec, domains=domains),
                    changes=diff(current, spec) if current else [],
                    cost_usd=cost,
                    model=model,
                    input_tokens=tokens[0],
                    output_tokens=tokens[1],
                )
        elif answer is not None:
            problems = ["the answer was a spec but carried none"]
        if attempt < REPAIRS:
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": "The engine refused that spec:\n- "
                    + "\n- ".join(problems)
                    + "\nFix it if the person's words allow; otherwise ask them.",
                }
            )
    return Compiled(
        "question",
        "This can't run as described: "
        + " ".join(problems)
        + " What would you like to change?",
        problems=problems,
        cost_usd=cost,
        model=model,
        input_tokens=tokens[0],
        output_tokens=tokens[1],
    )


def as_json(compiled: Compiled) -> dict[str, Any]:
    """The compiled answer as plain JSON, for the web layer and the record."""
    return {
        "kind": compiled.kind,
        "message": compiled.message,
        "choices": compiled.choices,
        "remember": compiled.remember,
        "spec": json.loads(compiled.spec.model_dump_json()) if compiled.spec else None,
        "rendering": compiled.rendering,
        "changes": [list(c) for c in compiled.changes],
        "problems": compiled.problems,
        "cost_usd": compiled.cost_usd,
        "model": compiled.model,
    }
