"""The research assistant (plan, task 54).

A person asks about markets, evidence and their strategies; a Claude model
answers by calling tools over the data, never from memory, and its answer
passes the number gate (`vp.strategy.gate`) before anyone reads it. The
loop is the manual tool-use loop with three guards (docs/strategies.md):

* **No progress.** Eight tool calls in a row whose results were all seen
  before in the turn stop it with a visible request for direction.
* **Repeated failure.** A call identical to one that failed is refused
  from its second attempt, without running it.
* **Budgets.** Model calls and wall-clock time per turn, tokens and turns
  per conversation; ``progress`` is called before each step, so a job's
  cancellation (which raises there) stops the turn, and the cost so far
  is reported as it runs.

The engine's tools read a data root: markets open now and settled, one
market in full, cutoff-bounded evidence, a preview of a candidate spec,
the domain packs and the glossary. The platform adds the person's own
strategies, their run cards and paper records, and starting a backtest
(`vp.platform.research`). No tool fetches the web.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from datetime import time as day_start
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vp.domains import DOMAINS
from vp.domains.pack import load as load_pack
from vp.forecast.evidence import Evidence, canonical, settled_at
from vp.forecast.llm import usage_usd
from vp.markets.store import read_markets
from vp.strategy import gate
from vp.strategy.spec import Spec, validate

MODEL = "claude-opus-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
GLOSSARY = (
    Path(__file__).parent.parent / "ui" / "static" / "app" / "locales" / "en.json"
)

SYSTEM = """You are the research assistant of vibe-predict, a platform where people
build and test forecasting strategies for binary prediction-market contracts
with play money. You help a person understand markets, evidence and their
own strategies' results.

Rules:
- Answer only from what your tools return in this conversation. Every
  figure you write (a count, a price, a percentage, a score, money) must
  appear in a tool result; if you do not have a number, call a tool or say
  you do not have it. Do not estimate probabilities of your own.
- Evidence has a cutoff: nothing after it exists for that question.
- A strategy is made or changed by the person describing it on the
  strategy page, where they confirm exactly what will run; you may suggest
  what to say, and you may preview a candidate spec with the preview tool.
- Nothing here is financial advice or a recommendation to bet; balances
  are play money. Say so if asked to recommend a real bet.
- Be brief and plain. Name which tool a figure came from when it matters.
"""


class ToolError(Exception):
    """A tool could not answer; the model is told why."""


def tool_schema(
    name: str, description: str, properties: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


_DOMAIN = {"type": "string", "enum": sorted(DOMAINS)}


class ToolBox:
    """The engine's research tools over a data root."""

    def __init__(
        self,
        root: Path,
        *,
        packs: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> None:
        self.root = root
        self.packs = dict(packs or {})
        self.now = now or datetime.now(tz=UTC)

    def definitions(self) -> list[dict[str, Any]]:
        return [
            tool_schema(
                "search_markets",
                "Find markets in a domain whose question contains the words: open "
                "now (from the newest capture, with prices) or settled (with the "
                "outcome). At most `limit` rows.",
                {
                    "domain": _DOMAIN,
                    "words": {"type": "string"},
                    "open_now": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            ),
            tool_schema(
                "explain_market",
                "One market in full: question, outcomes, parsed fields, price, fee, "
                "end date, outcome if settled, and its resolution rules.",
                {"domain": _DOMAIN, "market_id": {"type": "string"}},
            ),
            tool_schema(
                "evidence",
                "What was known before a cutoff date (YYYY-MM-DD, not in the "
                "future): a team's settled results in a match domain, or a city's "
                "daily highs in weather, newest first.",
                {
                    "domain": _DOMAIN,
                    "subject": {"type": "string"},
                    "cutoff": {"type": "string", "format": "date"},
                },
            ),
            tool_schema(
                "preview_spec",
                "Check a candidate strategy spec (JSON) and preview it: problems, "
                "markets open now, settled markets per month, cost, and the bets an "
                "edge would need.",
                {"spec_json": {"type": "string"}},
            ),
            tool_schema(
                "read_pack",
                "A domain pack section: how questions are phrased, fields, evidence "
                "and its cutoff, base rates, pitfalls. An empty section lists them.",
                {"domain": _DOMAIN, "section": {"type": "string"}},
            ),
            tool_schema(
                "glossary",
                "The platform's definition of a term (Brier score, skill, Kelly, "
                "spread, fee, ...).",
                {"term": {"type": "string"}},
            ),
        ]

    def run(self, name: str, args: dict[str, Any]) -> str:
        method = getattr(self, f"tool_{name}", None)
        if method is None:
            raise ToolError(f"there is no tool called {name}")
        return method(**args)

    # ----------------------------------------------------------- the tools

    def _open(self, domain: str) -> list[Any]:
        files = sorted((self.root / "snapshots" / domain).glob("*.parquet"))
        return read_markets(files[-1]) if files else []

    def _settled(self, domain: str) -> list[Any]:
        path = self.root / "markets" / domain / "resolved.parquet"
        return read_markets(path) if path.exists() else []

    def tool_search_markets(
        self, domain: str, words: str, open_now: bool, limit: int
    ) -> str:
        wanted = [w for w in words.lower().split() if w]
        pool = self._open(domain) if open_now else self._settled(domain)
        hits = [m for m in pool if all(w in m.question.lower() for w in wanted)]
        rows = []
        for m in hits[: max(1, min(limit, 25))]:
            kind = m.parsed.get("kind") or "unparsed"
            if open_now:
                rows.append(
                    f"{m.market_id} | {m.question} | {kind} | price {m.p_yes} | "
                    f"ends {m.end_date}"
                )
            else:
                won = {1: "first outcome won", 0: "first outcome lost"}.get(
                    m.resolved_outcome, "not settled"
                )
                when = settled_at(m)
                rows.append(
                    f"{m.market_id} | {m.question} | {kind} | {won} | "
                    f"settled {when.date() if when else 'unknown'}"
                )
        head = f"{len(hits)} {'open' if open_now else 'settled'} markets match"
        return "\n".join([head, *rows])

    def tool_explain_market(self, domain: str, market_id: str) -> str:
        for m in [*self._open(domain), *self._settled(domain)]:
            if m.market_id == market_id:
                first, second = m.outcomes
                return "\n".join(
                    [
                        f"question: {m.question}",
                        f"event: {m.event_title}",
                        f"outcomes: first {first.name}, second {second.name}",
                        f"parsed: {json.dumps(m.parsed, sort_keys=True)}",
                        f"price of the first outcome: {m.p_yes}",
                        f"bid {m.best_bid}, ask {m.best_ask}",
                        f"taker fee rate: {m.fee_rate}",
                        f"ends: {m.end_date}; status {m.status}; "
                        f"resolution {m.resolution_state}; label {m.resolved_outcome}",
                        f"resolution rules: {(m.description or 'not recorded')[:1500]}",
                    ]
                )
        raise ToolError(f"no market {market_id} in {domain} on this data root")

    def tool_evidence(self, domain: str, subject: str, cutoff: str) -> str:
        try:
            day = datetime.fromisoformat(cutoff).date()
        except ValueError:
            raise ToolError("the cutoff is a date, YYYY-MM-DD") from None
        at = datetime.combine(day, day_start(), tzinfo=UTC)
        if at > self.now:
            raise ToolError("a cutoff cannot be in the future")
        ev = Evidence(at, self.root)
        if domain == "weather":
            obs = ev.daily_highs(subject)[-15:]
            if not obs:
                return f"no daily highs for {subject} before {day}"
            return "\n".join(
                f"{o.day}: high in [{o.low}, {o.high}] {o.unit}" for o in reversed(obs)
            )
        team = canonical(subject)
        rows = [r for r in ev.results(domain) if team in (r.team_a, r.team_b)][-15:]
        if not rows:
            return f"no settled results for {subject} before {day}"
        return "\n".join(
            f"{r.settled.date()}: {r.team_a} vs {r.team_b}, winner {r.winner}"
            for r in reversed(rows)
        )

    def tool_preview_spec(self, spec_json: str) -> str:
        from vp.strategy.preview import preview

        try:
            spec = Spec.model_validate_json(spec_json)
        except ValidationError as exc:
            raise ToolError(
                "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                    for e in exc.errors()
                )
            ) from None
        problems = validate(spec)
        if problems:
            return "problems: " + " ".join(problems)
        return json.dumps(preview(spec, self.root).as_json())

    def tool_read_pack(self, domain: str, section: str) -> str:
        pack = load_pack(domain, self.packs.get(domain))
        if pack is None:
            raise ToolError(f"no pack for {domain}")
        if not section.strip():
            return f"{pack.summary}\nsections: {', '.join(pack.sections())}"
        text = pack.section(section)
        if text is None:
            raise ToolError(f"no section {section!r}; sections: {pack.sections()}")
        return text

    def tool_glossary(self, term: str) -> str:
        entries = json.loads(GLOSSARY.read_text())["glossary"]
        wanted = term.strip().lower()
        for key, entry in entries.items():
            if wanted in (key, entry.get("name", "").lower()):
                return f"{entry['name']}: {entry['text']}"
        raise ToolError(f"no glossary entry for {term!r}")


@dataclass
class Limits:
    """The guards' thresholds."""

    model_calls: int = 12  # per turn
    no_progress: int = 8  # tool calls in a row with nothing new
    seconds: float = 180.0  # per turn
    session_tokens: int = 400_000
    session_turns: int = 40


@dataclass
class Turn:
    """One answered message."""

    text: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    stopped: str | None = None  # why the turn ended early, if it did
    gate: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = MODEL

    def as_json(self) -> dict[str, Any]:
        return {"kind": "research", **asdict(self)}


STOPPED_TEXT = {
    "no_progress": "I looked at several things without finding anything new, so I "
    "stopped here. Tell me what to look at next.",
    "calls": "This question needed more steps than one answer may take. Ask a "
    "narrower question, or ask me to carry on.",
    "time": "This took too long, so I stopped. Ask a narrower question.",
    "session": "This conversation has reached its limit. Start a new one to carry on.",
    "declined": "The model declined to answer this.",
}


def research_turn(
    words: str,
    *,
    client: Any,
    tools: ToolBox,
    history: Sequence[tuple[str, str]] = (),
    limits: Limits = Limits(),
    used_tokens: int = 0,
    used_turns: int = 0,
    progress: Callable[[float, str], None] | None = None,
    model: str = MODEL,
    clock: Callable[[], float] = time.monotonic,
) -> Turn:
    """Answer one message: the tool loop, its guards, then the number gate."""
    if used_turns >= limits.session_turns or used_tokens >= limits.session_tokens:
        return Turn(STOPPED_TEXT["session"], stopped="session", model=model)
    turn = Turn("", model=model)
    messages: list[dict[str, Any]] = [
        {"role": role, "content": text} for role, text in history
    ]
    messages.append({"role": "user", "content": words})
    sources = [words]  # the figures the person gave may be repeated
    seen: set[str] = set()
    failed: set[str] = set()
    stale = 0
    regenerated = False
    started = clock()
    definitions = tools.definitions()
    for step in range(limits.model_calls):
        if clock() - started > limits.seconds:
            turn.stopped = "time"
            break
        if progress is not None:
            progress(
                step / limits.model_calls,
                f"thinking (${turn.cost_usd:.3f} so far)",
            )
        response = client.beta.messages.create(
            model=model,
            max_tokens=8000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            system=[
                {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
            ],
            tools=definitions,
            messages=messages,
        )
        turn.cost_usd += usage_usd(response.usage, model)
        turn.input_tokens += response.usage.input_tokens
        turn.output_tokens += response.usage.output_tokens
        if response.stop_reason == "refusal":
            turn.stopped = "declined"
            break
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                args = dict(block.input)
                key = block.name + json.dumps(args, sort_keys=True)
                if key in failed:
                    content, error = (
                        "refused: this exact call already failed; change it or stop",
                        True,
                    )
                else:
                    if progress is not None:
                        progress(step / limits.model_calls, f"using {block.name}")
                    try:
                        content, error = tools.run(block.name, args), False
                    except ToolError as exc:
                        content, error = f"error: {exc}", True
                        failed.add(key)
                digest = hashlib.sha256(content.encode()).hexdigest()
                stale = stale + 1 if digest in seen else 0
                seen.add(digest)
                if not error:
                    sources.append(content)
                turn.tools.append(
                    {"name": block.name, "input": args, "result": content[:4000]}
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                        "is_error": error,
                    }
                )
            messages.append({"role": "user", "content": results})
            if stale >= limits.no_progress:
                turn.stopped = "no_progress"
                break
            continue
        draft = "".join(b.text for b in response.content if b.type == "text").strip()
        failing = gate.check(draft, sources)
        if failing and not regenerated:
            regenerated = True
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": "Your answer states figures that are in no tool result: "
                    + ", ".join(f.text for f in failing)
                    + ". Rewrite it without them, or call a tool that gives them.",
                }
            )
            continue
        turn.gate = {
            "passed": not failing,
            "regenerated": regenerated,
            "replaced": [f.text for f in failing],
            "figures": len(gate.figures(draft)),
        }
        turn.text = gate.redact(draft, failing)
        return turn
    else:
        turn.stopped = "calls"
    turn.text = STOPPED_TEXT[turn.stopped or "calls"]
    return turn
