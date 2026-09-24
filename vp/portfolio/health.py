"""Strategy health (docs/portfolio.md, task 101).

A one-sided CUSUM on the standardised paired Brier advantage over the
market ($d > 0$ is better than the market) watches for a strategy that has
stopped beating it. $H = 18$ and $k = 0.25$ were chosen by simulation: at
par, fewer than 5% of strategies are falsely declared decayed within 500
settlements (docs/portfolio.md). A state must hold for two consecutive
settlements before it is adopted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np

from vp.strategy.card import paired_interval

K, H = 0.25, 18.0
# A strategy whose advantage barely varies (a constant forecast against
# near-certain prices) would divide by almost nothing; measured on the
# stand-in, the CUSUM reached 1.2e10. The floor is one Brier point in 100.
SD_FLOOR = 0.01
MIN_SETTLED, WINDOW, HOLD = 20, 25, 2


def _raw(t: int, s: float, window: np.ndarray) -> str:
    if t + 1 < MIN_SETTLED:
        return "too_early"
    if s > H:
        return "decayed"
    interval = paired_interval(window) if window.size >= WINDOW else None
    if s > H / 2 or (interval is not None and interval[2] < 0):
        return "watch"
    return "healthy"


def evaluate(
    advantages: Iterable[float], times: Sequence[str] | None = None
) -> dict[str, Any]:
    """The state after each settlement, the transitions and the CUSUM path."""
    d = np.asarray(list(advantages), dtype=float)
    state, pending, run = "too_early", None, 0
    s, path, transitions = 0.0, [], []
    c = c2 = 0.0
    for t, x in enumerate(d):
        c, c2 = c + x, c2 + x * x
        if t >= 2:
            mean = c / (t + 1)
            var = (c2 - (t + 1) * mean * mean) / t
            z = x / max(var**0.5 if var > 0 else 0.0, SD_FLOOR)
        else:
            z = 0.0
        s = max(0.0, s - z - K)
        path.append(s)
        raw = _raw(t, s, d[max(0, t + 1 - WINDOW) : t + 1])
        if raw == state:
            pending, run = None, 0
            continue
        run = run + 1 if raw == pending else 1
        pending = raw
        if run >= HOLD or state == "too_early":
            transitions.append(
                {
                    "settled": t + 1,
                    "from": state,
                    "to": raw,
                    "cusum": round(s, 3),
                    "at": times[t] if times else None,
                }
            )
            state, pending, run = raw, None, 0
    recent = d[-WINDOW:]
    interval = paired_interval(recent) if recent.size >= 2 else None
    return {
        "state": state,
        "settled": int(d.size),
        "cusum": round(s, 3),
        "threshold": H,
        "transitions": transitions,
        "path": [round(x, 3) for x in path[-200:]],
        "recent": None
        if interval is None
        else {"mean": interval[0], "low": interval[1], "high": interval[2]},
    }
