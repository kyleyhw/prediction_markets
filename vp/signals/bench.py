"""The signal bench (plan, task 65; docs/signals.md).

Every signal that applies to a domain is asked for each settled market in
the window at its cutoff (``hours`` before settlement), beside the market's
own price there. Each signal is paired with the market on the markets it
answered, and scored by the mean Brier difference (market minus signal, so
positive is better than the market) with a paired bootstrap 95% interval,
the Brier skill, and calibration. A signal is **alive** when the interval
lies above zero, **anti** when below, **at par** otherwise; the power
statement is the number of markets the observed difference would need to
be told from zero; the same difference per quarter shows decay. The output
names the command, the dataset file's size and time and each signal's
module hash, so one command reproduces every number.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from vp.backtest import scoring
from vp.forecast.evidence import Evidence, settled_at
from vp.markets.store import read_markets
from vp.signals import registry
from vp.strategy.card import needed_n, paired_interval

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MIN_N = 20


def _quarter(when: datetime) -> str:
    return f"{when.year}Q{(when.month - 1) // 3 + 1}"


def verdict(interval: tuple[float, float, float] | None) -> str:
    if interval is None:
        return "too few"
    return "alive" if interval[1] > 0 else "anti" if interval[2] < 0 else "par"


def bench(
    root: Path,
    domain: str,
    *,
    hours: float = 24.0,
    window: tuple[str, str] | None = None,
    max_markets: int | None = 2000,
    seed: int = 0,
    signal_ids: list[str] | None = None,
    blends: list[str] | None = None,
) -> dict[str, Any]:
    """Bench the signals on one domain; returns the JSON the page draws."""
    path = root / "markets" / domain / "resolved.parquet"
    resolved = read_markets(path)
    # Only a market with a stored price history can be scored against the
    # market, so the sample is drawn from those.
    priced = {h.stem for h in (root / "histories" / domain).glob("*.parquet")}
    markets = [
        m
        for m in resolved
        if m.resolved_outcome is not None and settled_at(m) and m.market_id in priced
    ]
    if window is not None:
        lo, hi = window
        markets = [m for m in markets if lo <= str(settled_at(m))[:7] <= hi]
    if max_markets is not None and len(markets) > max_markets:
        picked = np.random.default_rng(seed).choice(
            len(markets), max_markets, replace=False
        )
        markets = [markets[i] for i in sorted(picked)]
    markets.sort(key=lambda m: settled_at(m) or EPOCH)
    chosen = [registry.load(s) for s in (signal_ids or registry.ids())]
    signals = [s for s in chosen if any(s.meta.applies(m) for m in markets)]
    from vp.signals.blend import Blend

    mixes = [Blend(tuple(b.split("+"))) for b in blends or []]
    base = Evidence(EPOCH, root, markets={domain: resolved})
    rows: dict[str, list[tuple[datetime, float, float, int]]] = defaultdict(list)
    with_price = 0
    for m in markets:
        when = settled_at(m)
        assert when is not None
        ev = base.at(when - timedelta(hours=hours))
        q = ev.price_at(m)
        if q is None:
            continue
        with_price += 1
        for s in signals:
            if not s.meta.applies(m):
                continue
            p = s.compute(m, ev)
            if p is not None:
                rows[s.meta.id].append((when, p, q, int(m.resolved_outcome or 0)))
        for mix in mixes:
            answer = mix.forecast(m, ev)
            if answer is not None:
                rows[mix.name].append(
                    (when, answer.p_hat, q, int(m.resolved_outcome or 0))
                )
    out: dict[str, Any] = {}
    entries = [
        (s.meta.id, s.meta.title, s.meta.uses_price, registry.module_hash(s))
        for s in signals
    ] + [(mix.name, "Blend of " + ", ".join(mix.signal_ids), True, "") for mix in mixes]
    for key, title, uses_price, digest in entries:
        data = rows[key]
        entry: dict[str, Any] = {
            "title": title,
            "n": len(data),
            "uses_price": uses_price,
            "module_sha256": digest,
        }
        if len(data) >= MIN_N:
            p = np.clip(np.array([r[1] for r in data]), 0.01, 0.99)
            q = np.clip(np.array([r[2] for r in data]), 0.01, 0.99)
            y = np.array([r[3] for r in data], dtype=float)
            diffs = scoring.brier(q, y) - scoring.brier(p, y)
            interval = paired_interval(diffs, seed)
            cal = scoring.calibration(p, y)
            by_quarter: dict[str, list[float]] = defaultdict(list)
            for r, d in zip(data, diffs, strict=True):
                by_quarter[_quarter(r[0])].append(float(d))
            entry.update(
                {
                    "brier": float(scoring.brier(p, y).mean()),
                    "brier_market": float(scoring.brier(q, y).mean()),
                    "skill": scoring.skill(scoring.brier(p, y), scoring.brier(q, y)),
                    "advantage": None
                    if interval is None
                    else {"mean": interval[0], "low": interval[1], "high": interval[2]},
                    "verdict": verdict(interval),
                    "needed_n": needed_n(diffs),
                    "calibration": {
                        "reliability": cal.reliability,
                        "resolution": cal.resolution,
                        "ece": cal.expected_calibration_error,
                    },
                    "quarters": [
                        {"quarter": k, "n": len(v), "advantage": float(np.mean(v))}
                        for k, v in sorted(by_quarter.items())
                    ],
                }
            )
        else:
            entry["verdict"] = "too few"
        out[key] = entry
    stat = path.stat()
    return {
        "domain": domain,
        "hours": hours,
        "window": list(window) if window else None,
        "markets": len(markets),
        "with_price": with_price,
        "seed": seed,
        "dataset": {"bytes": stat.st_size, "modified": int(stat.st_mtime)},
        "command": f"vp signals bench --domain {domain} --hours {hours:g}"
        + (f" --window {window[0]}..{window[1]}" if window else "")
        + (f" --max-markets {max_markets}" if max_markets else "")
        + f" --seed {seed}"
        + "".join(f" --blend {b}" for b in blends or []),
        "signals": out,
    }
