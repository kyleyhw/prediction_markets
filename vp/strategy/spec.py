"""The strategy spec, version 1: a strategy as data (docs/strategies.md).

A spec says which markets (``Selector``), where the probability comes from
(``Belief``), when to trade (``Rule``), how much (``Sizing``) and when
(``Schedule``). It is typed and closed: an unknown field is refused, so a
constraint a person asked for can never be dropped on the way in. It is
rendered back into plain language by :func:`render`, deterministically and
without a model, so the words a person confirms are a function of the spec
that runs. A confirmed version is its canonical JSON and that JSON's hash
(:func:`canonical`, :func:`spec_hash`); :func:`diff` says what changed
between two versions.

Risk settings a prompt may only tighten are checked by :func:`validate`
against :class:`Caps`: the platform's defaults are the ceilings (decided
2026-09-19 as F6), and a workspace may set dollar and count caps of its
own.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vp.domains import DOMAINS, Domain

SPEC_VERSION = 1


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldFilter(_Closed):
    """A condition on one parsed field of a market."""

    field: str = Field(description="a parsed field of the selected kinds")
    op: Literal["is", "is_not", "contains", "at_least", "at_most"] = Field(
        description="is/is_not/contains: any of the values, ignoring case; "
        "at_least/at_most: one number"
    )
    values: list[str] = Field(min_length=1)


class Selector(_Closed):
    """Which markets the strategy considers."""

    domains: list[str] = Field(min_length=1)
    kinds: list[str] = Field(
        default_factory=list,
        description="parsed kinds; empty means the domains' main contracts",
    )
    where: list[FieldFilter] = Field(default_factory=list)
    words: list[str] = Field(
        default_factory=list, description="the question contains one of these"
    )
    exclude_words: list[str] = Field(
        default_factory=list, description="the question contains none of these"
    )
    min_volume_usd: float | None = Field(default=None, ge=0, description="paper only")
    min_liquidity_usd: float | None = Field(
        default=None, ge=0, description="paper only"
    )
    max_spread: float | None = Field(default=None, gt=0, le=1, description="paper only")


class Belief(_Closed):
    """Where the probability comes from."""

    forecaster: str = Field(default="market", description="a registered forecaster")
    instructions: str = Field(
        default="", max_length=4000, description="the person's guidance; llm only"
    )
    tier: Literal["standard", "strong"] = "standard"
    samples: int = Field(default=1, ge=1, le=5)
    sees_price: bool = Field(
        default=False, description="llm only: shown the market's price (F7)"
    )


class Rule(_Closed):
    """When to trade."""

    kind: Literal["edge", "follow"] = "edge"
    min_edge: float = Field(default=0.03, ge=0, le=1)
    sides: Literal["both", "yes", "no"] = "both"
    follow: Literal["favourite", "underdog"] | None = None
    price_min: float = Field(default=0.0, ge=0, le=1)
    price_max: float = Field(default=1.0, ge=0, le=1)


class Sizing(_Closed):
    """How much."""

    kelly_fraction: float = Field(default=0.25, gt=0, le=1)
    max_fraction: float = Field(default=0.05, gt=0, le=1)
    flat_fraction: float = Field(default=0.01, gt=0, le=1)
    max_stake_usd: float | None = Field(default=None, gt=0)
    max_open: int | None = Field(default=None, ge=1)
    max_per_event: int | None = Field(default=None, ge=1)
    initial_cash: float = Field(default=1000.0, gt=0, le=1_000_000)


class Schedule(_Closed):
    """When."""

    hours_before_close: float = Field(default=24.0, gt=0, le=24 * 60)
    cadence_hours: int = Field(default=1, ge=1, le=24)


class Spec(_Closed):
    """A strategy, version 1."""

    version: Literal[1] = SPEC_VERSION
    name: str = Field(min_length=1, max_length=100)
    idea: str = Field(default="", max_length=2000, description="the person's words")
    selector: Selector
    belief: Belief = Belief()
    rule: Rule = Rule()
    sizing: Sizing = Sizing()
    schedule: Schedule = Schedule()


@dataclass(frozen=True)
class Caps:
    """The loosest risk settings a spec may carry.

    The defaults are the platform's (F6); a workspace owner may set the
    dollar and count caps, a prompt never.
    """

    kelly_fraction: float = 0.25
    max_fraction: float = 0.05
    flat_fraction: float = 0.01
    min_edge: float = 0.03
    max_stake_usd: float | None = None
    max_open: int | None = None
    max_per_event: int | None = None


def canonical(spec: Spec) -> str:
    """The spec's canonical JSON: sorted keys, no spaces."""
    return json.dumps(
        spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )


def spec_hash(spec: Spec) -> str:
    """SHA-256 of the canonical JSON: the version's identity."""
    return hashlib.sha256(canonical(spec).encode()).hexdigest()


def validate(
    spec: Spec,
    caps: Caps = Caps(),
    *,
    domains: Mapping[str, Domain] = DOMAINS,
    forecasters: Iterable[str] | None = None,
) -> list[str]:
    """What is wrong with the spec, as plain sentences; empty when it may run."""
    if forecasters is None:
        from vp.forecast import forecaster_names

        forecasters = forecaster_names()
    known = set(forecasters)
    problems: list[str] = []
    sel, belief, rule, sizing = spec.selector, spec.belief, spec.rule, spec.sizing
    chosen = [domains[d] for d in sel.domains if d in domains]
    for name in sel.domains:
        if name not in domains:
            problems.append(f"There is no domain called {name!r}.")
    kinds: dict[str, tuple[str, ...]] = {}
    for domain in chosen:
        kinds.update(domain.all_kinds)
    for kind in sel.kinds:
        if kind not in kinds:
            problems.append(f"The chosen domains have no markets of kind {kind!r}.")
    fields = {
        f
        for kind, names in kinds.items()
        if (kind in sel.kinds if sel.kinds else any(kind in d.kinds for d in chosen))
        for f in names
    }
    for condition in sel.where:
        if chosen and condition.field not in fields:
            problems.append(
                f"The chosen markets have no field {condition.field!r} to filter on."
            )
        if condition.op in ("at_least", "at_most"):
            if len(condition.values) != 1 or _number(condition.values[0]) is None:
                problems.append(
                    f"{condition.op} on {condition.field} needs one number."
                )
    if belief.forecaster not in known:
        problems.append(f"There is no forecaster called {belief.forecaster!r}.")
    if belief.forecaster != "llm" and (belief.instructions or belief.sees_price):
        problems.append(
            "Instructions and showing the price apply only to the AI model."
        )
    if rule.kind == "follow":
        if rule.follow is None:
            problems.append(
                "A follow rule must say whether it backs the favourite or the underdog."
            )
        if belief.forecaster != "market":
            problems.append(
                "A follow rule makes no forecast; its belief must be the market."
            )
    elif belief.forecaster == "market":
        problems.append(
            "An edge rule needs a belief other than the market's own price,"
            " which never beats itself."
        )
    if rule.kind == "edge" and rule.follow is not None:
        problems.append("Only a follow rule backs the favourite or the underdog.")
    if rule.price_min >= rule.price_max:
        problems.append("The lowest price must be below the highest.")
    limits = [
        ("kelly_fraction", sizing.kelly_fraction, caps.kelly_fraction, "at most"),
        ("max_fraction", sizing.max_fraction, caps.max_fraction, "at most"),
        ("flat_fraction", sizing.flat_fraction, caps.flat_fraction, "at most"),
        ("min_edge", rule.min_edge, caps.min_edge, "at least"),
    ]
    for name, value, cap, way in limits:
        if (value > cap) if way == "at most" else (value < cap):
            problems.append(
                f"{_LIMIT_NAMES[name]} must be {way} {_LIMIT_SHOW[name](cap)}."
            )
    for name, cap in (
        ("max_stake_usd", caps.max_stake_usd),
        ("max_open", caps.max_open),
        ("max_per_event", caps.max_per_event),
    ):
        value = getattr(sizing, name)
        if cap is not None and (value is None or value > cap):
            problems.append(
                f"{_LIMIT_NAMES[name]} must be at most {_LIMIT_SHOW[name](cap)}."
            )
    return problems


_LIMIT_NAMES = {
    "kelly_fraction": "The share of the Kelly stake",
    "max_fraction": "The most staked on one market",
    "flat_fraction": "A follow rule's stake",
    "min_edge": "The smallest edge",
    "max_stake_usd": "The most staked on one market, in dollars,",
    "max_open": "The number of open positions",
    "max_per_event": "The number of positions in one event",
}
_LIMIT_SHOW: dict[str, Any] = {
    "kelly_fraction": lambda v: f"{v:g}",
    "max_fraction": lambda v: _pct(v) + " of the balance",
    "flat_fraction": lambda v: _pct(v) + " of the balance",
    "min_edge": lambda v: _points(v),
    "max_stake_usd": lambda v: _usd(v),
    "max_open": lambda v: f"{v}",
    "max_per_event": lambda v: f"{v}",
}


# ------------------------------------------------------------------ render

KIND_NAMES = {
    "match": "match results",
    "tournament_winner": "tournament winners",
    "season_winner": "season winners",
    "daily_temperature": "daily temperature ranges",
    "record_rank": "record rankings",
    "global_anomaly": "global temperature anomalies",
    "total": "over/under totals",
    "team_total": "team totals",
    "spread": "spreads and handicaps",
    "exact_score": "exact scores",
    "halftime_result": "halftime results",
    "second_half_result": "second-half results",
    "both_teams_to_score": "both teams to score",
    "anytime_scorer": "anytime goalscorers",
    "first_to_score": "first to score",
    "first_corner": "first corner",
    "odd_even": "odd or even totals",
}

FORECASTER_NAMES_PLAIN = {
    "market": "the market's own price",
    "constant": "a fixed 50% chance for every market",
    "climatology": "climatology: how often past days at the city fell in the range",
    "elo": "Elo ratings from past results",
    "llm": "an AI model reading the evidence",
}


def plain_name(forecaster: str) -> str:
    """A forecaster's name in words: a signal by its title."""
    if forecaster.startswith("signal:"):
        from vp.signals.registry import load

        try:
            return f"the signal “{load(forecaster.removeprefix('signal:')).meta.title}”"
        except ValueError:
            return forecaster
    return FORECASTER_NAMES_PLAIN.get(forecaster, forecaster)


_OPS = {
    "is": "is",
    "is_not": "is not",
    "contains": "contains",
    "at_least": "is at least",
    "at_most": "is at most",
}


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _usd(v: float) -> str:
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def _pct(v: float) -> str:
    return f"{v * 100:g}%"


def _points(v: float) -> str:
    n = v * 100
    return f"{n:g} point" + ("" if n == 1 else "s")


def _cents(v: float) -> str:
    return f"{v * 100:g}¢"


def _either(values: list[str]) -> str:
    quoted = [f"“{v}”" for v in values]
    return (
        quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " or " + quoted[-1]
    )


def render(spec: Spec, *, domains: Mapping[str, Domain] = DOMAINS) -> list[str]:
    """The spec in plain sentences, one per part; the same spec, the same words."""
    return [
        _render_markets(spec.selector, domains),
        _render_belief(spec),
        _render_trade(spec.rule),
        _render_size(spec.rule, spec.sizing),
        _render_when(spec.schedule, spec.sizing),
    ]


def _render_markets(sel: Selector, domains: Mapping[str, Domain]) -> str:
    titles = [domains[d].title if d in domains else d for d in sel.domains]
    kinds = (
        ", ".join(KIND_NAMES.get(k, k.replace("_", " ")) for k in sel.kinds)
        if sel.kinds
        else "their main markets"
    )
    text = f"Markets: {' and '.join(titles)}, {kinds}"
    for c in sel.where:
        text += f"; where {c.field.replace('_', ' ')} {_OPS[c.op]} {_either(c.values)}"
    if sel.words:
        text += f"; only questions mentioning {_either(sel.words)}"
    if sel.exclude_words:
        text += f"; never questions mentioning {_either(sel.exclude_words)}"
    text += "."
    floors = []
    if sel.min_volume_usd is not None:
        floors.append(f"at least {_usd(sel.min_volume_usd)} traded")
    if sel.min_liquidity_usd is not None:
        floors.append(f"at least {_usd(sel.min_liquidity_usd)} of liquidity")
    if sel.max_spread is not None:
        floors.append(f"a spread of at most {_cents(sel.max_spread)}")
    if floors:
        text += (
            " In paper only, a market also needs "
            + ", ".join(floors)
            + " (a backtest cannot know these as they were)."
        )
    return text


def _render_belief(spec: Spec) -> str:
    b = spec.belief
    if spec.rule.kind == "follow":
        return "Belief: none. It follows the market's own prices and makes no forecast."
    text = "Belief: " + plain_name(b.forecaster)
    if b.forecaster != "llm":
        return text + "."
    from vp.forecast.llm import TIERS

    text += f" ({b.tier} tier, {TIERS[b.tier]})"
    text += (
        ", asked once per market"
        if b.samples == 1
        else (f", asked {b.samples} times per market and averaged")
    )
    if b.instructions:
        text += f", with your instructions: “{b.instructions}”"
    if b.sees_price:
        return text + (
            ". It is shown the market's price, so its record is labelled"
            " and left out of skill rankings."
        )
    return text + ". It is not shown the market's price."


def _render_trade(rule: Rule) -> str:
    band = ""
    if rule.price_min > 0 or rule.price_max < 1:
        low, high = _cents(rule.price_min), _cents(rule.price_max)
        band = f" only when the price is between {low} and {high}"
    if rule.kind == "follow":
        side = "favourite" if rule.follow == "favourite" else "underdog"
        return (
            f"Trade: buys the {side} of every market" + (band or " at any price") + "."
        )
    sides = {
        "both": "on either side",
        "yes": "only on the first outcome (usually “Yes”)",
        "no": "only against the first outcome",
    }[rule.sides]
    text = (
        f"Trade: when its chance beats the price after fees by at least "
        f"{_points(rule.min_edge)}, {sides}"
    )
    return text + (f",{band}" if band else "") + "."


def _render_size(rule: Rule, s: Sizing) -> str:
    if rule.kind == "follow":
        text = (
            f"Size: {_pct(min(s.flat_fraction, s.max_fraction))} of the balance on each"
        )
    else:
        text = (
            f"Size: {s.kelly_fraction:g} of the Kelly stake, at most "
            f"{_pct(s.max_fraction)} of the balance on one market"
        )
    if s.max_stake_usd is not None:
        text += f" and never more than {_usd(s.max_stake_usd)}"
    if s.max_open is not None:
        text += f"; at most {s.max_open} open at once"
    if s.max_per_event is not None:
        text += f"; at most {s.max_per_event} in one event"
    if s.max_open is not None or s.max_per_event is not None:
        text += " (in paper; a backtest settles each bet before the next)"
    return text + "."


def _render_when(sch: Schedule, s: Sizing) -> str:
    every = (
        "every hour" if sch.cadence_hours == 1 else f"every {sch.cadence_hours} hours"
    )
    return (
        f"When: from {sch.hours_before_close:g} hours before a market's scheduled "
        f"end, checked {every}; a backtest forecasts each market "
        f"{sch.hours_before_close:g} hours before it settled. Starts with "
        f"{_usd(s.initial_cash)} of play money."
    )


# -------------------------------------------------------------------- diff


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: value}


def diff(old: Spec, new: Spec) -> list[tuple[str, Any, Any]]:
    """Changed fields as ``(path, old value, new value)``, in path order."""
    a = _flatten(old.model_dump(mode="json"))
    b = _flatten(new.model_dump(mode="json"))
    return [
        (path, a.get(path), b.get(path))
        for path in sorted(a.keys() | b.keys())
        if a.get(path) != b.get(path)
    ]
