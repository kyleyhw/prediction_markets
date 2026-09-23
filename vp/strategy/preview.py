"""The preview: what a spec would touch, before anything runs (task 53).

From data only, never from a model: the open markets its selector picks in
the newest snapshot of each domain, with example questions; the resolved
markets it would have picked, per month of settlement (the backtest's
universe) and how many of those have a stored price history (the backtest
can score only those); the estimated cost of a backtest and of a month of
paper when the belief is the AI model; and the power statement.

**The power statement.** A bet bought at price $p$ returns $1/p - 1$ per
dollar with probability $p$ and $-1$ otherwise; if the belief is right by
an edge $\\delta$ the mean return per dollar is about $\\delta / p$ and its
standard deviation about $\\sqrt{(1 - p)/p}$. Telling a mean of $\\delta/p$
from zero at the 5% level with 80% power takes

$$n \\approx \\left(\\frac{(z_{0.975} + z_{0.8})\\sqrt{(1-p)/p}}{\\delta/p}\\right)^2
= \\frac{(1.96 + 0.84)^2\\, p (1 - p)}{\\delta^2}$$

settled bets. At $p = 0.5$ and a 3-point edge that is about 2,200; at a
1-point edge about 19,600. The preview states it at the price band's
midpoint (0.5 without a band) for the spec's minimum edge, beside how many
markets the selector settled a month, so a person sees how long a paper
run must last before its result means anything.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vp.forecast.evidence import settled_at
from vp.markets.store import read_markets
from vp.strategy.run import selects
from vp.strategy.spec import Spec

#: z for a two-sided 5% test plus z for 80% power.
Z = 1.96 + 0.84
#: Markets an LLM backtest samples by default (F8).
LLM_SAMPLE = 100


def bets_needed(edge: float, price: float = 0.5) -> int:
    """Settled bets needed to tell an edge at this price from zero."""
    if edge <= 0:
        return 0
    return round(Z**2 * price * (1 - price) / edge**2)


@dataclass
class Preview:
    """What the spec would touch, per domain and in total."""

    open_now: int = 0
    examples: list[str] = field(default_factory=list)
    resolved: int = 0
    with_history: int = 0
    per_month: dict[str, int] = field(default_factory=dict)
    settled_a_month: float = 0.0
    backtest_markets: int = 0
    backtest_usd: float = 0.0
    paper_month_usd: float = 0.0
    bets_needed: int = 0
    edge: float = 0.0
    price: float = 0.5
    notes: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def _newest(root: Path, domain: str) -> Path | None:
    files = sorted((root / "snapshots" / domain).glob("*.parquet"))
    return files[-1] if files else None


def preview(
    spec: Spec, root: Path, *, snapshots: dict[str, Path] | None = None
) -> Preview:
    """The preview of ``spec`` over the data root.

    ``snapshots`` names the snapshot to read per domain; by default the
    newest file under ``root/snapshots/<domain>/``.
    """
    out = Preview()
    live, past = selects(spec.selector, live=True), selects(spec.selector, live=False)
    months: Counter[str] = Counter()
    for domain in spec.selector.domains:
        snap = (snapshots or {}).get(domain) or _newest(root, domain)
        if snap is not None and snap.exists():
            picked = [m for m in read_markets(snap) if live(m)]
            out.open_now += len(picked)
            out.examples += [m.question for m in picked[: 5 - len(out.examples)]]
        path = root / "markets" / domain / "resolved.parquet"
        if not path.exists():
            out.notes.append(f"No resolved {domain} markets on this data root yet.")
            continue
        histories = root / "histories" / domain
        for m in read_markets(path):
            when = settled_at(m)
            if m.resolved_outcome is None or when is None or not past(m):
                continue
            out.resolved += 1
            months[when.strftime("%Y-%m")] += 1
            if (histories / f"{m.market_id}.parquet").exists():
                out.with_history += 1
    out.per_month = dict(sorted(months.items()))
    if months:
        recent = sorted(months)[-12:]
        out.settled_a_month = sum(months[k] for k in recent) / len(recent)
    rule = spec.rule
    out.price = (rule.price_min + rule.price_max) / 2
    out.edge = rule.min_edge
    if rule.kind == "edge":
        out.bets_needed = bets_needed(out.edge, out.price)
    else:
        out.notes.append(
            "A follow rule makes no forecast; its result is P&L only, and its"
            " spread against zero decides how long it must run."
        )
    b = spec.belief
    if b.forecaster == "llm" and rule.kind == "edge":
        from vp.forecast.llm import TIERS, estimate_usd

        model = TIERS[b.tier]
        out.backtest_markets = min(out.with_history, LLM_SAMPLE)
        out.backtest_usd = estimate_usd(
            out.backtest_markets, model, samples=b.samples, batch=True
        )
        # Paper asks the belief again each cycle while a market is in its
        # window and has no position: at most window / cadence times.
        asks = spec.schedule.hours_before_close / spec.schedule.cadence_hours
        out.paper_month_usd = estimate_usd(
            round(out.settled_a_month * asks), model, samples=b.samples
        )
    if spec.selector.min_volume_usd or spec.selector.min_liquidity_usd:
        out.notes.append("Volume and liquidity floors apply in paper only.")
    if spec.selector.max_spread:
        out.notes.append("The spread ceiling applies in paper only.")
    if spec.sizing.max_open or spec.sizing.max_per_event:
        out.notes.append(
            "Open-position caps bind in paper only; a backtest settles each bet"
            " before the next."
        )
    return out
