"""What a record says about the person as a forecaster (docs/shadow.md,
task 93).

Every quantity is about the side the person bought. With entry price $p$,
closing price $c$ and $y$ whether that side won: edge is $y - p$,
closing-line value is $c - p$, and skill against the close is
$1 - \\sum (p - y)^2 / \\sum (c - y)^2$. A measure is reported only with
``MIN_BETS`` bets behind it; intervals are bootstrap intervals over bets.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from statistics import median
from typing import Any

import numpy as np

from vp.shadow.record import Bet
from vp.strategy.card import paired_interval

MIN_BETS = 10
BANDS = [i / 10 for i in range(11)]
LONGSHOT, FAVOURITE = 0.2, 0.8
CHASE = 0.05  # a rise of five points in the day before the first buy
EPS = 1e-6


def _interval(values: list[float]) -> dict[str, float] | None:
    got = paired_interval(np.array(values)) if len(values) >= MIN_BETS else None
    return None if got is None else {"mean": got[0], "low": got[1], "high": got[2]}


def _ret(bets: list[Bet]) -> float | None:
    cost = sum(b.cost for b in bets)
    return sum(b.pnl for b in bets) / cost if cost else None


def _rank_corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < MIN_BETS or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    rx = np.argsort(np.argsort(xs)).astype(float)
    ry = np.argsort(np.argsort(ys)).astype(float)
    return float(np.corrcoef(rx, ry)[0, 1])


def taker_fee(bet: Bet, assumed: float) -> float:
    """The fee the buys would have paid as takers: an upper bound."""
    rate = bet.fee_rate if bet.fee_rate is not None else assumed
    p = bet.entry
    return bet.bought * rate * (p * (1 - p)) ** (bet.fee_exponent or 1.0)


def summary(bets: list[Bet]) -> dict[str, Any]:
    """The headline measures of a set of bets."""
    scored = [b for b in bets if b.scored]
    y = [1.0 if b.won else 0.0 for b in scored]
    out: dict[str, Any] = {
        "bets": len(bets),
        "scored": len(scored),
        "staked": round(sum(b.cost for b in scored), 2),
        "pnl": round(sum(b.pnl for b in scored), 2),
        "return": _ret(scored),
        "win_rate": sum(y) / len(y) if y else None,
        "mean_entry": sum(b.entry for b in scored) / len(scored) if scored else None,
        "edge": _interval([yi - b.entry for yi, b in zip(y, scored, strict=True)]),
    }
    priced = [b for b in scored if b.close is not None]
    out["priced"] = len(priced)
    if len(priced) >= MIN_BETS:
        yp = np.array([1.0 if b.won else 0.0 for b in priced])
        p = np.clip(np.array([b.entry for b in priced]), EPS, 1 - EPS)
        c = np.clip(np.array([b.close for b in priced], dtype=float), EPS, 1 - EPS)
        brier_p, brier_c = (p - yp) ** 2, (c - yp) ** 2
        log_p = -(yp * np.log(p) + (1 - yp) * np.log(1 - p))
        log_c = -(yp * np.log(c) + (1 - yp) * np.log(1 - c))
        out["brier"] = {"entry": float(brier_p.mean()), "close": float(brier_c.mean())}
        out["log_loss"] = {"entry": float(log_p.mean()), "close": float(log_c.mean())}
        out["skill_vs_close"] = (
            float(1 - brier_p.sum() / brier_c.sum()) if brier_c.sum() else None
        )
        out["skill_interval"] = _interval(list(brier_c - brier_p))
        out["clv"] = _interval(list(c - p))
        out["clv_positive"] = float((c > p).mean())
    return out


def calibration(scored: list[Bet]) -> list[dict[str, Any]]:
    rows = []
    for lo, hi in zip(BANDS, BANDS[1:], strict=False):
        inside = [b for b in scored if lo <= b.entry < hi or (hi == 1 and b.entry == 1)]
        if not inside:
            continue
        rows.append(
            {
                "band": [lo, hi],
                "bets": len(inside),
                "mean_price": sum(b.entry for b in inside) / len(inside),
                "win_rate": sum(1 for b in inside if b.won) / len(inside),
                "stake_share": sum(b.cost for b in inside)
                / max(sum(b.cost for b in scored), EPS),
            }
        )
    return rows


def habits(scored: list[Bet], assumed_fee: float) -> dict[str, Any]:
    stakes = [b.cost for b in scored]
    total = sum(stakes) or EPS
    longshots = [b for b in scored if b.entry < LONGSHOT]
    favourites = [b for b in scored if b.entry >= FAVOURITE]
    holds = [
        (
            (b.last_at if b.sold else (b.closed_at or b.last_at)) - b.first_at
        ).total_seconds()
        / 3600
        for b in scored
    ]
    early = [b for b in scored if b.sold > 0]
    kept = [b for b in scored if b.sold == 0]
    chased = [b for b in scored if b.before is not None and b.entry - b.before >= CHASE]
    calm = [b for b in scored if b.before is not None and b.entry - b.before < CHASE]
    clv = [b for b in scored if b.close is not None]
    fees = sum(taker_fee(b, assumed_fee) for b in scored)
    gross = sum(b.pnl for b in scored)
    top = sorted(stakes, reverse=True)[: max(len(stakes) // 10, 1)]

    def clv_mean(bets: list[Bet]) -> float | None:
        vals = [b.close - b.entry for b in bets if b.close is not None]
        return sum(vals) / len(vals) if len(vals) >= MIN_BETS else None

    return {
        "longshot": {
            "stake_share": sum(b.cost for b in longshots) / total,
            "bets": len(longshots),
            "win_rate": sum(1 for b in longshots if b.won) / len(longshots)
            if longshots
            else None,
            "mean_price": sum(b.entry for b in longshots) / len(longshots)
            if longshots
            else None,
        },
        "favourite": {
            "stake_share": sum(b.cost for b in favourites) / total,
            "bets": len(favourites),
            "win_rate": sum(1 for b in favourites if b.won) / len(favourites)
            if favourites
            else None,
            "mean_price": sum(b.entry for b in favourites) / len(favourites)
            if favourites
            else None,
        },
        "holding_hours_median": median(holds) if holds else None,
        "fills_per_bet": sum(b.fills for b in scored) / len(scored) if scored else None,
        "sold_early_share": len(early) / len(scored) if scored else None,
        "return_sold_early": _ret(early) if len(early) >= MIN_BETS else None,
        "return_held": _ret(kept) if len(kept) >= MIN_BETS else None,
        "chased_share": len(chased) / len(chased + calm) if chased or calm else None,
        "clv_chased": clv_mean(chased),
        "clv_calm": clv_mean(calm),
        "stake_cv": float(np.std(stakes) / np.mean(stakes))
        if len(stakes) >= MIN_BETS
        else None,
        "stake_clv_corr": _rank_corr(
            [b.cost for b in clv],
            [b.close - b.entry for b in clv if b.close is not None],
        ),
        "top_tenth_stake_share": sum(top) / total,
        "fees_upper_bound": round(fees, 2),
        "fee_drag": fees / gross if gross > 0 else None,
    }


def _group(bets: list[Bet], key: Callable[[Bet], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Bet]] = defaultdict(list)
    for b in bets:
        groups[key(b)].append(b)
    return {
        k: summary(v)
        for k, v in sorted(groups.items())
        if sum(1 for b in v if b.scored) >= MIN_BETS
    }


def diagnose(bets: list[Bet], assumed_fee: float = 0.05) -> dict[str, Any]:
    """Every diagnostic of a record's bets."""
    scored = [b for b in bets if b.scored]
    out = {
        "overall": summary(bets),
        "calibration": calibration(scored),
        "habits": habits(scored, assumed_fee),
        "by_domain": _group(bets, lambda b: b.domain or "other"),
        "by_month": _group(bets, lambda b: b.first_at.strftime("%Y-%m")),
    }
    return _finite(out)


def _finite(value: Any) -> Any:
    """NaN and infinities become None, so the result is valid JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value
