"""The Research Lab's studies that are not already a command (plan, task
123; docs/lab/). Each reads a data root, returns markdown, and prints the
same thing every time on the same data, so a page quoting it can be
checked by rerunning it (`vp lab check`).

A study never names a domain: the domain is an argument, as in every other
command.
"""

from __future__ import annotations

import json
import math
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np

from vp.backtest import scoring
from vp.backtest.run import BacktestConfig, run_backtest, select_markets
from vp.backtest.sizing import FeeModel, fees_for
from vp.forecast import Evidence
from vp.forecast.evidence import settled_at
from vp.markets.store import read_markets

Z_95 = 1.959964
Z_ONE_SIDED_95 = 1.644854
Z_POWER_80 = 0.841621


def _wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(centre - half, 0.0), min(centre + half, 1.0))  # never "-0.000"


def prices_at_cutoff(
    root: Path, domain: str, hours: float, kinds: tuple[str, ...] = ()
) -> list[tuple[float, int, FeeModel]]:
    """(market price at the cutoff, outcome, the market's fee model) for every
    labelled market with a price ``hours`` before settlement."""
    from datetime import UTC, datetime

    resolved = read_markets(root / "markets" / domain / "resolved.parquet")
    markets = select_markets(resolved, BacktestConfig(domain, kinds=kinds))
    base = Evidence(datetime(1970, 1, 1, tzinfo=UTC), root, markets={domain: resolved})
    out = []
    for m in markets:
        when = settled_at(m)
        assert when is not None
        q = base.at(when - timedelta(hours=hours)).price_at(m)
        if q is not None and m.resolved_outcome is not None:
            out.append((float(q), int(m.resolved_outcome), fees_for(m, FeeModel())[0]))
    return out


def event_sums(root: Path, domain: str, hours: float) -> list[float]:
    """For each event of mutually exclusive markets (the venue's negative-risk
    events: one day's buckets, one match's three results) whose every market
    has a price at the cutoff, the sum of those prices."""
    from datetime import UTC, datetime

    resolved = read_markets(root / "markets" / domain / "resolved.parquet")
    events: dict[str, list] = {}
    for m in resolved:
        if m.neg_risk and m.event_id:
            events.setdefault(m.event_id, []).append(m)
    base = Evidence(datetime(1970, 1, 1, tzinfo=UTC), root, markets={domain: resolved})
    out = []
    for members in events.values():
        settled = [t for t in (settled_at(m) for m in members) if t is not None]
        when = max(settled, default=None)
        if when is None or len(members) < 2:
            continue
        ev = base.at(when - timedelta(hours=hours))
        prices = [ev.price_at(m) for m in members]
        if all(q is not None for q in prices):
            out.append(float(sum(q for q in prices if q is not None)))
    return out


def longshot(
    root: Path,
    domain: str,
    hours: float = 24.0,
    half_spread: float = 0.01,
    edges: tuple[float, ...] = (0.0, 0.05, 0.15, 0.3, 0.5, 0.7, 0.85, 0.95, 1.0),
) -> str:
    """The favourite-longshot bias: does a contract priced q win q of the time?

    Markets are binned by their price at the cutoff. For each bin: how many,
    the mean price, how often the event happened with its 95% Wilson
    interval, and what buying every contract in the bin at the ask
    (price plus the half-spread) and the market's own taker fee returned per
    dollar staked. A bias shows as low bins winning less often than priced
    and high bins more often.
    """
    rows = prices_at_cutoff(root, domain, hours)
    lines = [
        f"{len(rows)} labelled {domain} markets with a price {hours:g} h before "
        f"settlement; buying at the price plus {half_spread} and the market's fee.",
        "",
        "| Price bin | Markets | Mean price | Won | 95% interval "
        "| Return per $1 at the ask |",
        "| :--- | ---: | ---: | ---: | :--- | ---: |",
    ]
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        cell = [
            (q, y, f) for q, y, f in rows if lo <= q < hi or (hi == 1.0 and q == 1.0)
        ]
        if not cell:
            continue
        k = sum(y for _, y, _ in cell)
        a, b = _wilson(k, len(cell))
        returns = []
        for q, y, fee in cell:
            ask = min(q + half_spread, 0.99)
            returns.append((y - ask - fee.per_share(ask)) / ask)
        lines.append(
            f"| {lo:.2f} to {hi:.2f} | {len(cell)} | "
            f"{np.mean([q for q, _, _ in cell]):.3f} | "
            f"{k / len(cell):.3f} | [{a:.3f}, {b:.3f}] | {np.mean(returns):+.3f} |"
        )
    sums = event_sums(root, domain, hours)
    if sums:
        lines += [
            "",
            f"{len(sums)} events of mutually exclusive markets had every market "
            f"priced; their prices summed to {np.median(sums):.3f} at the median "
            f"(middle half {np.quantile(sums, 0.25):.3f} to "
            f"{np.quantile(sums, 0.75):.3f}), where fair prices sum to 1.",
        ]
    q_all = np.array([q for q, _, _ in rows])
    y_all = np.array([y for _, y, _ in rows], dtype=float)
    if rows:
        q_clip = np.clip(q_all, 0.01, 0.99)
        cal = scoring.calibration(q_clip, y_all)
        lines += [
            "",
            f"Market Brier {float(scoring.brier(q_clip, y_all).mean()):.4f}, "
            f"reliability {cal.reliability:.4f}, resolution {cal.resolution:.4f}.",
        ]
    return "\n".join(lines) + "\n"


def power(
    root: Path,
    domain: str,
    forecaster: str,
    hours: float = 24.0,
    skills: tuple[float, ...] = (0.01, 0.02, 0.05, 0.1),
    sharpes: tuple[float, ...] = (0.05, 0.1, 0.2),
) -> str:
    """How many settled markets a claim of edge needs.

    The forecaster and the market are scored on the same markets (the
    backtest's common set). The spread of the per-market Brier difference
    gives the number of markets needed to show a given skill against the
    market with 95% confidence and 80% power; the second table does the same
    for a per-bet Sharpe ratio, where a bootstrap's P(Sharpe > 0) of 0.95
    needs about (1.645 / Sharpe)² bets.
    """
    with tempfile.TemporaryDirectory() as scratch:
        config = BacktestConfig(
            domain, forecasters=("market", forecaster), hours_before_close=hours
        )
        run_backtest(config, root, Path(scratch))
        rows = [json.loads(line) for line in (Path(scratch) / "forecasts.jsonl").open()]
    resolved = {
        m.market_id: m.resolved_outcome
        for m in read_markets(root / "markets" / domain / "resolved.parquet")
    }
    by: dict[str, dict[str, float]] = {}
    for r in rows:
        by.setdefault(r["market_id"], {})[r["forecaster"]] = float(r["p_hat"])
    pairs = [
        (v["market"], v[forecaster], resolved[k])
        for k, v in by.items()
        if "market" in v and forecaster in v and resolved.get(k) is not None
    ]
    q = np.clip(np.array([a for a, _, _ in pairs]), 0.01, 0.99)
    p = np.array([b for _, b, _ in pairs])
    y = np.array([c for _, _, c in pairs], dtype=float)
    ref = scoring.brier(q, y)
    d = scoring.brier(p, y) - ref  # negative is better than the market
    n = len(d)
    if n < 3:
        return f"{n} markets scored; too few to say anything.\n"
    sd = float(d.std(ddof=1))
    mean_ref = float(ref.mean())
    half = Z_95 * sd / math.sqrt(n)
    skill = -float(d.mean()) / mean_ref
    lines = [
        f"`{forecaster}` against the market on {n} {domain} markets, {hours:g} h "
        "before settlement.",
        "",
        f"Skill {skill:+.4f}, 95% interval [{skill - half / mean_ref:+.4f}, "
        f"{skill + half / mean_ref:+.4f}]. Per-market Brier difference: mean "
        f"{d.mean():+.4f}, standard deviation {sd:.4f}; the market's mean Brier "
        f"{mean_ref:.4f}.",
        "",
        "| True skill against the market "
        "| Markets needed (95% confidence, 80% power) |",
        "| ---: | ---: |",
    ]
    for s in skills:
        delta = s * mean_ref
        need = ((Z_ONE_SIDED_95 + Z_POWER_80) * sd / delta) ** 2
        lines.append(f"| {s:+.2f} | {math.ceil(need):,} |")
    lines += [
        "",
        "| Per-bet Sharpe | Bets for P(Sharpe > 0) of 0.95 |",
        "| ---: | ---: |",
    ]
    lines += [
        f"| {s:.2f} | {math.ceil((Z_ONE_SIDED_95 / s) ** 2):,} |" for s in sharpes
    ]
    return "\n".join(lines) + "\n"


def by_event(
    root: Path,
    domain: str,
    signal_id: str,
    hours: float = 24.0,
    n_boot: int = 2000,
    seed: int = 0,
) -> str:
    """A signal's advantage over the market with the interval resampled by
    event, not by market.

    The bench's paired bootstrap treats every market as independent. The
    markets of one event are not: one day's temperature buckets are
    mutually exclusive and settle together, so a model that is right about
    a day is right about several markets at once. Resampling whole events
    gives the interval the data can actually support.
    """
    from datetime import UTC, datetime

    from vp.signals import registry
    from vp.strategy.card import paired_interval

    resolved = read_markets(root / "markets" / domain / "resolved.parquet")
    priced = {h.stem for h in (root / "histories" / domain).glob("*.parquet")}
    signal = registry.load(signal_id)
    base = Evidence(datetime(1970, 1, 1, tzinfo=UTC), root, markets={domain: resolved})
    groups: dict[str, list[float]] = {}
    for m in resolved:
        when = settled_at(m)
        if m.resolved_outcome is None or when is None or m.market_id not in priced:
            continue
        if not signal.meta.applies(m):
            continue
        ev = base.at(when - timedelta(hours=hours))
        q = ev.price_at(m)
        p = signal.compute(m, ev) if q is not None else None
        if q is None or p is None:
            continue
        y = float(m.resolved_outcome)
        q_c, p_c = min(max(q, 0.01), 0.99), min(max(p, 0.01), 0.99)
        diff = (q_c - y) ** 2 - (p_c - y) ** 2  # positive: better than the market
        groups.setdefault(m.event_id or m.market_id or "", []).append(diff)
    diffs = np.array([d for g in groups.values() for d in g])
    if len(diffs) < 3:
        return f"{len(diffs)} markets scored; too few to say anything.\n"
    mean = float(diffs.mean())
    market_level = paired_interval(diffs, seed)
    assert market_level is not None  # three or more markets
    _, lo_m, hi_m = market_level
    sums = np.array([sum(g) for g in groups.values()])
    sizes = np.array([len(g) for g in groups.values()])
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(groups), size=(n_boot, len(groups)))
    boot = sums[pick].sum(axis=1) / sizes[pick].sum(axis=1)
    lo_e, hi_e = (float(x) for x in np.quantile(boot, [0.025, 0.975]))

    def verdict(lo: float, hi: float) -> str:
        return "better than the market" if lo > 0 else "worse" if hi < 0 else "at par"

    return (
        f"`{signal_id}` against the market on {len(diffs)} {domain} markets in "
        f"{len(groups)} events, {hours:g} h before settlement; Brier advantage "
        "(positive is better than the market).\n\n"
        "| Resampling | Mean advantage | 95% interval | Verdict |\n"
        "| :--- | ---: | :--- | :--- |\n"
        f"| by market | {mean:+.4f} | [{lo_m:+.4f}, {hi_m:+.4f}] | "
        f"{verdict(lo_m, hi_m)} |\n"
        f"| by event | {mean:+.4f} | [{lo_e:+.4f}, {hi_e:+.4f}] | "
        f"{verdict(lo_e, hi_e)} |\n"
    )
