"""Rules that describe when and which side a person bet (docs/shadow.md,
task 94).

A candidate rule is exactly what the strategy spec can express: a domain,
a kind, a side (favourite or underdog), a price band for that side, a time
before close, and at most one parsed-field condition. So a validated rule
is a spec draft by construction.

Positives are the person's bets; negatives are the dataset's markets of the
same domain that closed while the person was active and that they did not
bet, priced from their histories at the rule's time before close. The
negatives are a sample, so each stands for ``weight`` markets. Rules are
fitted greedily on the first 70% of the record by time and validated on
the rest.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import numpy as np

from vp.shadow.record import Bet, Series
from vp.strategy.spec import FieldFilter, Schedule, Selector, Spec
from vp.strategy.spec import Rule as SpecRule

Side = Literal["favourite", "underdog"]
SIDES: tuple[Side, Side] = ("favourite", "underdog")
HOURS = (1, 3, 6, 12, 24, 48, 72, 168)
GRID = tuple(round(0.05 * i, 2) for i in range(1, 20))
FORMATION = 0.7
MAX_RULES = 3
FIELDS, VALUES, MIN_VALUE_BETS = 5, 5, 5
# Validation on the held-out part (docs/shadow.md).
MIN_COVERAGE, MIN_AGREEMENT, MIN_LIFT, MIN_HELD_OUT = 0.25, 0.8, 3.0, 10


@dataclass(frozen=True)
class Rule:
    domain: str
    kind: str
    side: Side
    price_min: float
    price_max: float
    hours: int
    field: str | None = None
    value: str | None = None

    def words(self) -> str:
        where = f", where {self.field} is {self.value}" if self.field else ""
        return (
            f"Buys the {self.side} in {self.kind} markets when it is priced "
            f"{self.price_min:.0%} to {self.price_max:.0%}, about {self.hours} "
            f"hours before the close{where}."
        )

    def spec(self, name: str) -> Spec:
        where = (
            [FieldFilter(field=self.field, op="is", values=[str(self.value)])]
            if self.field
            else []
        )
        return Spec(
            name=name[:100],
            idea=self.words(),
            selector=Selector(domains=[self.domain], kinds=[self.kind], where=where),
            rule=SpecRule(
                kind="follow",
                follow=self.side,
                price_min=self.price_min,
                price_max=self.price_max,
            ),
            schedule=Schedule(hours_before_close=float(self.hours)),
        )


def from_spec(spec: Spec) -> Rule | None:
    """The rule a spec expresses, if it is one this search can validate."""
    s, r = spec.selector, spec.rule
    if (
        r.kind != "follow"
        or r.follow is None
        or len(s.domains) != 1
        or len(s.kinds) != 1
        or len(s.where) > 1
        or s.words
        or s.exclude_words
    ):
        return None
    cond = s.where[0] if s.where else None
    if cond is not None and (cond.op != "is" or len(cond.values) != 1):
        return None
    return Rule(
        s.domains[0],
        s.kinds[0],
        r.follow,
        r.price_min,
        r.price_max,
        nearest_hours(spec.schedule.hours_before_close),
        cond.field if cond else None,
        cond.values[0] if cond else None,
    )


def nearest_hours(hours: float) -> int:
    h = max(hours, 0.25)
    return min(HOURS, key=lambda x: abs(math.log(x) - math.log(h)))


@dataclass
class Market:
    """A market the person could have bet: a negative example."""

    market_id: str
    kind: str
    parsed: dict[str, str]
    closed_at: datetime
    series: Series  # the first outcome's price
    won_first: bool | None = None  # settlement evidence only

    def first_price(self, hours: int) -> float | None:
        t = (self.closed_at - timedelta(hours=hours)).timestamp()
        first = None
        for at, p in self.series:
            if at > t:
                break
            first = p
        return first

    def side_price(self, side: str, hours: int) -> float | None:
        first = self.first_price(hours)
        if first is None:
            return None
        fav = max(first, 1 - first)
        return fav if side == "favourite" else 1 - fav


def _bet_side(bet: Bet) -> str:
    return "favourite" if bet.favourite else "underdog"


def _side_price(bet: Bet, side: str) -> float:
    return bet.entry if _bet_side(bet) == side else 1 - bet.entry


def _field_ok(parsed: dict[str, str], field: str | None, value: str | None) -> bool:
    return field is None or (parsed.get(field) or "").lower() == str(value).lower()


def covers(rule: Rule, bet: Bet) -> tuple[bool, bool]:
    """(the rule would have been in this bet's market then, on its side)."""
    hbc = bet.hours_before_close
    if (
        bet.parsed.get("kind") != rule.kind
        or hbc is None
        or nearest_hours(hbc) != rule.hours
        or not _field_ok(bet.parsed, rule.field, rule.value)
    ):
        return False, False
    inside = rule.price_min <= _side_price(bet, rule.side) <= rule.price_max
    return inside, inside and _bet_side(bet) == rule.side


def selects(rule: Rule, market: Market) -> bool:
    if market.kind != rule.kind or not _field_ok(market.parsed, rule.field, rule.value):
        return False
    p = market.side_price(rule.side, rule.hours)
    return p is not None and rule.price_min <= p <= rule.price_max


def evaluate(
    rule: Rule, bets: list[Bet], markets: list[Market], weight: float
) -> dict[str, Any]:
    hits = [covers(rule, b) for b in bets]
    covered = sum(1 for c, _ in hits if c)
    agreed = sum(1 for _, a in hits if a)
    negatives = sum(1 for m in markets if selects(rule, m)) * weight
    base = len(bets) / (len(bets) + weight * len(markets)) if bets else 0.0
    precision = agreed / (agreed + negatives) if agreed + negatives else 0.0
    return {
        "bets": len(bets),
        "agreed": agreed,
        "coverage": agreed / len(bets) if bets else 0.0,
        "agreement": agreed / covered if covered else 0.0,
        "precision": precision,
        "lift": precision / base if base else 0.0,
    }


def validated(held_out: dict[str, Any]) -> bool:
    return (
        held_out["coverage"] >= MIN_COVERAGE
        and held_out["agreement"] >= MIN_AGREEMENT
        and held_out["lift"] >= MIN_LIFT
        and held_out["agreed"] >= MIN_HELD_OUT
    )


def _conditions(bets: list[Bet]) -> list[tuple[str | None, str | None]]:
    out: list[tuple[str | None, str | None]] = [(None, None)]
    fields = Counter(f for b in bets for f in b.parsed if f != "kind")
    for f, _ in fields.most_common(FIELDS):
        values = Counter(
            (b.parsed.get(f) or "").lower() for b in bets if b.parsed.get(f)
        )
        out += [(f, v) for v, n in values.most_common(VALUES) if n >= MIN_VALUE_BETS]
    return out


def _best(
    domain: str,
    bets: list[Bet],
    remaining: list[Bet],
    markets: list[Market],
    weight: float,
) -> tuple[Rule, float] | None:
    """The candidate with the best F1 on ``remaining`` bets (vectorised over
    price bands)."""
    lows = np.array(GRID)
    best: tuple[Rule, float] | None = None
    np.seterr(divide="ignore", invalid="ignore")
    base_n = len(remaining)
    if not base_n:
        return None
    for kind in sorted({k for b in bets if (k := b.parsed.get("kind"))}):
        of_kind = [b for b in remaining if b.parsed.get("kind") == kind]
        m_kind = [m for m in markets if m.kind == kind]
        for field, value in _conditions(
            [b for b in bets if b.parsed.get("kind") == kind]
        ):
            bk = [b for b in of_kind if _field_ok(b.parsed, field, value)]
            mk = [m for m in m_kind if _field_ok(m.parsed, field, value)]
            for hours in HOURS:
                timed = [
                    b
                    for b in bk
                    if b.hours_before_close is not None
                    and nearest_hours(b.hours_before_close) == hours
                ]
                for side in SIDES:
                    agree = np.array(
                        [_side_price(b, side) for b in timed if _bet_side(b) == side]
                    )
                    neg = np.array(
                        [p for m in mk if (p := m.side_price(side, hours)) is not None]
                    )
                    if agree.size == 0:
                        continue
                    for lo in lows:
                        highs = lows[lows > lo]
                        if highs.size == 0:
                            continue
                        a = ((agree[:, None] >= lo) & (agree[:, None] <= highs)).sum(0)
                        n = (
                            ((neg[:, None] >= lo) & (neg[:, None] <= highs)).sum(0)
                            if neg.size
                            else np.zeros(highs.size)
                        )
                        precision = np.where(
                            a + weight * n > 0, a / (a + weight * n), 0
                        )
                        recall = a / base_n
                        f1 = np.where(
                            precision + recall > 0,
                            2 * precision * recall / (precision + recall),
                            0,
                        )
                        i = int(np.argmax(f1))
                        if f1[i] > 0 and (best is None or f1[i] > best[1]):
                            best = (
                                Rule(
                                    domain,
                                    str(kind),
                                    side,
                                    float(lo),
                                    float(highs[i]),
                                    hours,
                                    field,
                                    value,
                                ),
                                float(f1[i]),
                            )
    return best


def extract(
    domain: str,
    bets: list[Bet],
    markets: list[Market],
    weight: float,
    *,
    proposed: Iterable[Spec] = (),
    name: str = "The rule version of me",
) -> dict[str, Any]:
    """Fit on the first 70% of the domain's bets by time, validate on the rest."""
    bets = sorted(
        (b for b in bets if b.domain == domain and b.hours_before_close is not None),
        key=lambda b: b.first_at,
    )
    if len(bets) < 2 * MIN_HELD_OUT:
        return {
            "domain": domain,
            "bets": len(bets),
            "rules": [],
            "reason": "too few bets",
        }
    cut = bets[int(len(bets) * FORMATION)].first_at
    fit_bets = [b for b in bets if b.first_at < cut]
    held_bets = [b for b in bets if b.first_at >= cut]
    fit_m = [m for m in markets if m.closed_at < cut]
    held_m = [m for m in markets if m.closed_at >= cut]
    chosen: list[tuple[Rule, str]] = []
    remaining = list(fit_bets)
    for _ in range(MAX_RULES):
        found = _best(domain, fit_bets, remaining, fit_m, weight)
        if found is None:
            break
        rule = found[0]
        chosen.append((rule, "enumerated"))
        remaining = [b for b in remaining if not covers(rule, b)[1]]
    for spec in proposed:
        rule = from_spec(spec)
        if rule is not None and rule.domain == domain:
            chosen.append((rule, "model"))
    out = []
    for rule, origin in chosen:
        held = evaluate(rule, held_bets, held_m, weight)
        ok = validated(held)
        out.append(
            {
                "rule": asdict(rule),
                "words": rule.words(),
                "origin": origin,
                "formation": evaluate(rule, fit_bets, fit_m, weight),
                "held_out": held,
                "validated": ok,
                "spec": rule.spec(name).model_dump(mode="json") if ok else None,
            }
        )
    return {
        "domain": domain,
        "bets": len(bets),
        "formation_bets": len(fit_bets),
        "held_out_bets": len(held_bets),
        "negatives": len(markets),
        "weight": weight,
        "split_at": cut.isoformat(),
        "rules": out,
    }
