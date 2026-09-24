"""The person against the rule version of them (docs/shadow.md, task 95).

All returns are per dollar staked and before fees, as the record's own
are (the venue's activity carries no fee). With $R_w$ the person's
stake-weighted return, $R_e$ the same bets equally weighted, $R_t$ the same
bets equally weighted at the rule's scheduled price and $R_r$ the rule's
equally weighted return on its own selection:

    R_w - R_r = (R_w - R_e) + (R_e - R_t) + (R_t - R_r)
                 sizing        timing        selection

Each part has a bootstrap interval. The market-following baseline, which
takes the market's price as the forecast, has an expected return of zero
before fees.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np

from vp.shadow.record import Bet
from vp.shadow.rules import Market, Rule, _field_ok, selects

DRAWS = 2_000


@dataclass
class Leg:
    """One bet of the comparison: the person's and the rule's price."""

    cost: float
    pnl: float
    won: bool
    scheduled: float  # the price of the bet's side at the rule's time


def _legs(bets: list[Bet], rule: Rule) -> list[Leg]:
    out = []
    for b in bets:
        if not b.scored or b.closed_at is None or b.domain != rule.domain:
            continue
        if b.parsed.get("kind") != rule.kind or not _field_ok(
            b.parsed, rule.field, rule.value
        ):
            continue
        q = b.price_at(b.closed_at - timedelta(hours=rule.hours))
        if q is None or not 0 < q < 1:
            continue
        out.append(Leg(b.cost, b.pnl, bool(b.won), q))
    return out


def _rule_returns(bets: list[Bet], markets: list[Market], rule: Rule) -> list[float]:
    """The rule's return per dollar on every market it selects."""
    out = []
    for m in markets:
        p1 = m.first_price(rule.hours)
        if not selects(rule, m) or m.won_first is None or p1 is None:
            continue
        side_is_first = (p1 >= 0.5) == (rule.side == "favourite")
        q = p1 if side_is_first else 1 - p1
        won = m.won_first if side_is_first else not m.won_first
        if 0 < q < 1:
            out.append((1.0 if won else 0.0) / q - 1)
    for b in bets:
        if not b.scored or b.closed_at is None or b.domain != rule.domain:
            continue
        if b.parsed.get("kind") != rule.kind or not _field_ok(
            b.parsed, rule.field, rule.value
        ):
            continue
        mine = b.price_at(b.closed_at - timedelta(hours=rule.hours))
        if mine is None or not 0 < mine < 1:
            continue
        mine_side = "favourite" if mine >= 0.5 else "underdog"
        q = mine if mine_side == rule.side else 1 - mine
        won = bool(b.won) if mine_side == rule.side else not b.won
        if rule.price_min <= q <= rule.price_max and 0 < q < 1:
            out.append((1.0 if won else 0.0) / q - 1)
    return out


def _parts(legs: list[Leg], rule_r: np.ndarray) -> tuple[float, float, float]:
    cost = np.array([x.cost for x in legs])
    pnl = np.array([x.pnl for x in legs])
    r_w = pnl.sum() / cost.sum()
    r_e = float((pnl / cost).mean())
    r_t = float(np.mean([(1.0 if x.won else 0.0) / x.scheduled - 1 for x in legs]))
    r_r = float(rule_r.mean())
    return float(r_w - r_e), r_e - r_t, r_t - r_r


def compare(
    bets: list[Bet], markets: list[Market], rule: Rule, seed: int = 0
) -> dict[str, Any] | None:
    legs = [x for x in _legs(bets, rule) if x.cost > 0]
    rule_r = np.array(_rule_returns(bets, markets, rule))
    if len(legs) < 10 or rule_r.size < 10:
        return None
    cost = np.array([x.cost for x in legs])
    pnl = np.array([x.pnl for x in legs])
    sizing, timing, selection = _parts(legs, rule_r)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(DRAWS):
        i = rng.integers(0, len(legs), len(legs))
        j = rng.integers(0, rule_r.size, rule_r.size)
        draws.append(_parts([legs[k] for k in i], rule_r[j]))
    arr = np.array(draws)

    def band(k: int, value: float) -> dict[str, float]:
        lo, hi = np.quantile(arr[:, k], [0.025, 0.975])
        return {"mean": value, "low": float(lo), "high": float(hi)}

    return {
        "bets": len(legs),
        "rule_markets": int(rule_r.size),
        "you": float(pnl.sum() / cost.sum()),
        "rule": float(rule_r.mean()),
        "market": 0.0,
        "sizing": band(0, sizing),
        "timing": band(1, timing),
        "selection": band(2, selection),
    }
