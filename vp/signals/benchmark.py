"""The public benchmark (plan, task 69; docs/signals.md).

Each week a question set is frozen from open markets across the domains,
drawn with a published seed; every configuration's forecasts on it are
written down and only a commitment is published, the SHA-256 of a random
salt and the forecasts' canonical JSON. When the questions resolve, the
forecasts and salts are revealed, anyone can recompute the commitments,
and the forecasts are scored against the outcomes and against the market's
price at freezing. Nothing is ranked below ``MIN_RANKED`` settled
questions. Commit-before-cutoff is what makes the scores trustworthy: a
forecast cannot be changed once its hash is out.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from vp.backtest import scoring
from vp.forecast.evidence import parse_time
from vp.markets.schema import BinaryMarket
from vp.strategy.card import paired_interval

SIZE = 50
HORIZON_DAYS = 30
MIN_RANKED = 50


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def week_of(when: datetime) -> str:
    year, week, _ = when.isocalendar()
    return f"{year}-W{week:02d}"


def freeze(
    markets: list[BinaryMarket],
    *,
    now: datetime,
    seed: int,
    size: int = SIZE,
    horizon_days: int = HORIZON_DAYS,
) -> dict[str, Any]:
    """The week's question set: open, parsed, priced markets ending within
    the horizon, drawn in turn from each domain with the seed."""
    horizon = now + timedelta(days=horizon_days)
    eligible: dict[str, list[BinaryMarket]] = {}
    for m in markets:
        end = parse_time(m.end_date)
        if (
            m.market_id
            and not m.trading_closed
            and m.parsed.get("kind")
            and m.p_yes is not None
            and 0.0 < m.p_yes < 1.0
            and end is not None
            and now < end <= horizon
        ):
            eligible.setdefault(m.domain or "", []).append(m)
    rng = np.random.default_rng(seed)
    pools = {
        d: [ms[i] for i in rng.permutation(len(ms))]
        for d, ms in sorted(eligible.items())
    }
    chosen: list[BinaryMarket] = []
    while len(chosen) < size and any(pools.values()):
        for d in list(pools):
            if pools[d] and len(chosen) < size:
                chosen.append(pools[d].pop())
    questions = [
        {
            "market_id": m.market_id,
            "condition_id": m.condition_id,
            "domain": m.domain,
            "question": m.question,
            "end_date": m.end_date,
            "price": m.p_yes,
        }
        for m in chosen
    ]
    body = {
        "week": week_of(now),
        "seed": seed,
        "frozen_at": now.isoformat(),
        "questions": questions,
    }
    return body | {"hash": hashlib.sha256(_canonical(body).encode()).hexdigest()}


def commit(week_hash: str, config: str, forecasts: dict[str, float]) -> dict[str, str]:
    """The commitment to one configuration's forecasts, with what reveals it.

    Publish ``commitment``; keep ``salt`` and ``payload`` until the reveal.
    """
    payload = _canonical(
        {
            "week": week_hash,
            "config": config,
            "forecasts": {k: round(v, 6) for k, v in sorted(forecasts.items())},
        }
    )
    salt = secrets.token_hex(16)
    commitment = hashlib.sha256((salt + payload).encode()).hexdigest()
    return {"commitment": commitment, "salt": salt, "payload": payload}


def verify(commitment: str, salt: str, payload: str) -> bool:
    """Whether a revealed salt and payload match the published commitment."""
    return hashlib.sha256((salt + payload).encode()).hexdigest() == commitment


def score(week: dict[str, Any], payload: str, labels: dict[str, int]) -> dict[str, Any]:
    """Score one revealed configuration on the settled questions."""
    forecasts = json.loads(payload)["forecasts"]
    rows = [
        (forecasts[q["market_id"]], q["price"], labels[q["market_id"]])
        for q in week["questions"]
        if q["market_id"] in forecasts and q["market_id"] in labels
    ]
    if not rows:
        return {"n": 0, "ranked": False}
    p = np.clip(np.array([r[0] for r in rows]), 0.01, 0.99)
    q = np.clip(np.array([r[1] for r in rows]), 0.01, 0.99)
    y = np.array([r[2] for r in rows], dtype=float)
    diffs = scoring.brier(q, y) - scoring.brier(p, y)
    interval = paired_interval(diffs)
    return {
        "n": len(rows),
        "brier": float(scoring.brier(p, y).mean()),
        "log": float(scoring.log_score(p, y).mean()),
        "skill": scoring.skill(scoring.brier(p, y), scoring.brier(q, y)),
        "advantage": None
        if interval is None
        else {"mean": interval[0], "low": interval[1], "high": interval[2]},
        "ranked": len(rows) >= MIN_RANKED,
    }
