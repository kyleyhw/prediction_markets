"""Leakage check: forward scores against backtest scores per forecaster.

The backtest scores a forecaster at cutoffs in the past; the forward loop
scores it at cutoffs that were the present when the forecast was made. If
the backtest evidence leaked anything from after its cutoffs, the backtest
scores are optimistic and the forward scores will be worse by more than
sampling noise. The check reports, per forecaster, the mean Brier score in
each setting and a bootstrap interval on the gap (forward minus backtest);
a gap whose interval excludes zero is the signal. The same scoring code is
used on both sides, so a gap cannot come from a scoring difference.

The comparison is fair only within a domain and for the same forecaster
configuration; it does not correct for the base rate differing between the
two market samples, which the summary makes visible by printing both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vp.backtest.scoring import brier_one
from vp.forecast.base import clip
from vp.markets.store import read_markets
from vp.paper.ledger import Ledger


@dataclass(frozen=True)
class Gap:
    forecaster: str
    n_backtest: int
    n_forward: int
    brier_backtest: float
    brier_forward: float
    gap: float
    gap_low: float
    gap_high: float


def backtest_scores(
    backtest_dir: Path, root: Path, domain: str
) -> dict[str, np.ndarray]:
    """Per-forecaster Brier scores of a backtest run, from its registry and labels."""
    labels = {
        m.market_id: m.resolved_outcome
        for m in read_markets(root / "markets" / domain / "resolved.parquet")
        if m.resolved_outcome is not None
    }
    scores: dict[str, list[float]] = {}
    with (backtest_dir / "forecasts.jsonl").open() as fh:
        for line in fh:
            row = json.loads(line)
            label = labels.get(row["market_id"])
            if label is None:
                continue
            scores.setdefault(row["forecaster"], []).append(
                brier_one(clip(row["p_hat"]), label)
            )
    return {k: np.array(v) for k, v in scores.items()}


def forward_scores(ledger: Ledger) -> dict[str, np.ndarray]:
    """Per-forecaster Brier scores of settled paper positions."""
    scores: dict[str, list[float]] = {}
    for entry in ledger.entries():
        if entry["kind"] == "settlement":
            d = entry["data"]
            scores.setdefault(d["forecaster"], []).append(d["brier"])
    return {k: np.array(v) for k, v in scores.items()}


def gaps(
    back: dict[str, np.ndarray],
    forward: dict[str, np.ndarray],
    *,
    seed: int = 0,
    n_bootstrap: int = 2000,
) -> list[Gap]:
    """Bootstrap the difference of means for every forecaster present in both."""
    rng = np.random.default_rng(seed)
    out: list[Gap] = []
    for name in sorted(set(back) & set(forward)):
        b, f = back[name], forward[name]
        if b.size == 0 or f.size == 0:
            continue
        draws = np.empty(n_bootstrap)
        for i in range(n_bootstrap):
            draws[i] = rng.choice(f, f.size).mean() - rng.choice(b, b.size).mean()
        out.append(
            Gap(
                name,
                b.size,
                f.size,
                float(b.mean()),
                float(f.mean()),
                float(f.mean() - b.mean()),
                float(np.percentile(draws, 2.5)),
                float(np.percentile(draws, 97.5)),
            )
        )
    return out


def summary(rows: list[Gap]) -> str:
    lines = [
        "| Forecaster | n backtest | Brier backtest | n forward | Brier forward "
        "| Gap | 95% CI |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for g in rows:
        lines.append(
            f"| {g.forecaster} | {g.n_backtest} | {g.brier_backtest:.4f} | "
            f"{g.n_forward} | {g.brier_forward:.4f} | {g.gap:+.4f} | "
            f"[{g.gap_low:+.4f}, {g.gap_high:+.4f}] |"
        )
    return "\n".join(lines) + "\n"
