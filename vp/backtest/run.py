"""The backtest: forecast every resolved market at a cutoff, score, simulate.

For each resolved market in a domain the cutoff is its settlement time
minus ``hours_before_close``; the evidence object is viewed at that cutoff,
every forecaster is asked, and the market's own price at the cutoff is the
reference. Only markets on which *every* forecaster answered and a price
exists are scored, so all forecasters are compared on the same set. Each
forecaster except the market itself is then run through the fill simulator
with the market's price as the quote, and the bankroll statistics of
``vp.backtest.bankroll`` are computed on its settled bets.

Outputs under ``out_dir``: ``forecasts.jsonl`` (the registry for the run),
``summary.md`` (the tables), ``results.json`` (the same numbers plus the
series behind the figures, which the dashboard draws itself), and three
figures: the reliability diagram per forecaster, the cumulative Brier
advantage over the market in settlement order, and the equity curves.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from vp.backtest import bankroll, scoring
from vp.backtest.simulate import Bet, Opportunity, simulate
from vp.backtest.sizing import FeeModel
from vp.forecast import Evidence, Forecaster, make_forecaster
from vp.forecast.base import Forecast
from vp.forecast.evidence import settled_at
from vp.forecast.registry import Registry
from vp.markets.schema import BinaryMarket
from vp.markets.store import read_markets

logger = logging.getLogger(__name__)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class BacktestConfig:
    """What to backtest and how."""

    domain: str
    forecasters: tuple[str, ...] = ("market", "constant")
    hours_before_close: float = 24.0
    kinds: tuple[str, ...] = ()
    max_markets: int | None = None
    seed: int = 0
    initial_cash: float = 1000.0
    half_spread: float = 0.01
    fee_rate: float = 0.0
    kelly_multiplier: float = 0.25
    max_fraction: float = 0.05
    min_edge: float = 0.0


@dataclass
class ForecasterResult:
    """Scores and simulated bets of one forecaster on the common set."""

    name: str
    n: int
    brier: float
    log: float
    skill: float
    calibration: scoring.Calibration
    cost_usd: float
    bets: list[Bet] = field(default_factory=list)
    stats: bankroll.BetStats | None = None
    sharpe: bankroll.BootstrapInterval | None = None


@dataclass
class BacktestResult:
    config: BacktestConfig
    candidates: int
    with_price: int
    common: int
    results: list[ForecasterResult]
    seconds: float


def select_markets(
    markets: list[BinaryMarket], config: BacktestConfig
) -> list[BinaryMarket]:
    """Labelled markets of the requested kinds, sampled and in settlement order."""
    rows = [
        m
        for m in markets
        if m.resolved_outcome is not None
        and settled_at(m) is not None
        and (not config.kinds or m.parsed.get("kind") in config.kinds)
    ]
    if config.max_markets is not None and len(rows) > config.max_markets:
        rng = np.random.default_rng(config.seed)
        index = rng.choice(len(rows), size=config.max_markets, replace=False)
        rows = [rows[i] for i in sorted(index)]
    rows.sort(key=lambda m: settled_at(m) or m.fetched_at)
    return rows


def run_backtest(
    config: BacktestConfig,
    root: Path,
    out_dir: Path,
    *,
    forecasters: Sequence[Forecaster] | None = None,
    llm_options: dict[str, object] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> BacktestResult:
    """Run the backtest and write its outputs; returns the result.

    ``progress``, when given, is called with the fraction of markets done
    and a short message as the forecasting loop advances, so a caller that
    runs this in the background can report how far it has got.
    """
    started = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = read_markets(root / "markets" / config.domain / "resolved.parquet")
    markets = select_markets(resolved, config)
    if forecasters is None:
        forecasters = [
            make_forecaster(name, config.domain, **(llm_options or {}))
            if name == "llm"
            else make_forecaster(name, config.domain)
            for name in config.forecasters
        ]
    registry = Registry(out_dir / "forecasts.jsonl")
    base = Evidence(_EPOCH, root, markets={config.domain: resolved})

    # forecasts[name] -> list aligned with `scored` markets
    scored: list[tuple[BinaryMarket, float, str]] = []
    forecasts: dict[str, list[Forecast]] = {f.name: [] for f in forecasters}
    with_price = 0
    for index, market in enumerate(markets):
        if progress is not None and index % 10 == 0:
            progress(index / max(len(markets), 1), f"{index} of {len(markets)} markets")
        when = settled_at(market)
        assert when is not None
        cutoff = when - timedelta(hours=config.hours_before_close)
        evidence = base.at(cutoff)
        q = evidence.price_at(market)
        if q is None:
            continue
        with_price += 1
        answers: list[Forecast] = []
        for forecaster in forecasters:
            answer = forecaster.forecast(market, evidence)
            if answer is None:
                break
            answers.append(answer)
        if len(answers) < len(forecasters):
            continue
        for answer in answers:
            registry.append(answer)
            forecasts[answer.forecaster].append(answer)
        scored.append((market, q, when.isoformat()))

    y = np.array([m.resolved_outcome for m, _, _ in scored], dtype=float)
    q_arr = np.array([q for _, q, _ in scored], dtype=float)
    reference = scoring.brier(np.clip(q_arr, 0.01, 0.99), y) if scored else np.array([])
    results: list[ForecasterResult] = []
    for forecaster in forecasters:
        rows = forecasts[forecaster.name]
        p = np.array([f.p_hat for f in rows], dtype=float)
        result = ForecasterResult(
            name=forecaster.name,
            n=len(rows),
            brier=float(scoring.brier(p, y).mean()) if rows else 0.0,
            log=float(scoring.log_score(p, y).mean()) if rows else 0.0,
            skill=scoring.skill(scoring.brier(p, y), reference) if rows else 0.0,
            calibration=scoring.calibration(p, y),
            cost_usd=sum(f.cost_usd for f in rows),
        )
        if forecaster.name != "market" and rows:
            opportunities = [
                Opportunity(
                    m.market_id or "", when, f.p_hat, q, int(m.resolved_outcome or 0)
                )
                for (m, q, when), f in zip(scored, rows, strict=True)
            ]
            result.bets = simulate(
                opportunities,
                initial_cash=config.initial_cash,
                half_spread=config.half_spread,
                fees=FeeModel(config.fee_rate),
                kelly_multiplier=config.kelly_multiplier,
                max_fraction=config.max_fraction,
                min_edge=config.min_edge,
            )
            pnl = np.array([b.pnl for b in result.bets], dtype=float)
            result.stats = bankroll.bet_stats(pnl, config.initial_cash)
            if pnl.size >= 3:
                result.sharpe = bankroll.bootstrap_sharpe(
                    pnl,
                    config.initial_cash,
                    n_bootstrap=1000,
                    confidence=0.95,
                    seed=config.seed,
                )
        results.append(result)

    outcome = BacktestResult(
        config,
        len(markets),
        with_price,
        len(scored),
        results,
        time.monotonic() - started,
    )
    (out_dir / "summary.md").write_text(summary(outcome))
    (out_dir / "results.json").write_text(
        json.dumps(results_json(outcome, forecasts, y, reference), indent=1)
    )
    if scored:
        plots(outcome, forecasts, y, reference, out_dir)
    return outcome


def results_json(
    result: BacktestResult,
    forecasts: dict[str, list[Forecast]],
    y: np.ndarray,
    reference: np.ndarray,
) -> dict[str, Any]:
    """Scores, calibration bins and the plotted series, as plain JSON."""
    out: dict[str, Any] = {
        "config": asdict(result.config),
        "candidates": result.candidates,
        "with_price": result.with_price,
        "common": result.common,
        "seconds": round(result.seconds, 2),
        "forecasters": [],
    }
    for r in result.results:
        p = np.array([f.p_hat for f in forecasts[r.name]], dtype=float)
        advantage = (
            np.cumsum(reference - scoring.brier(p, y)).tolist() if p.size else []
        )
        out["forecasters"].append(
            {
                "name": r.name,
                "n": r.n,
                "brier": r.brier,
                "log": r.log,
                "skill": r.skill,
                "cost_usd": r.cost_usd,
                "calibration": {
                    "reliability": r.calibration.reliability,
                    "resolution": r.calibration.resolution,
                    "uncertainty": r.calibration.uncertainty,
                    "ece": r.calibration.expected_calibration_error,
                    "bins": [asdict(b) for b in r.calibration.bins],
                },
                "advantage": advantage,
                "equity": [result.config.initial_cash]
                + [b.bankroll_after for b in r.bets],
                "stats": asdict(r.stats) if r.stats else None,
                "sharpe": asdict(r.sharpe) if r.sharpe else None,
            }
        )
    return out


def summary(result: BacktestResult) -> str:
    """Markdown tables of the run."""
    c = result.config
    lines = [
        f"# Backtest: {c.domain}",
        "",
        f"forecasters: {', '.join(c.forecasters)}; cutoff {c.hours_before_close} h "
        f"before settlement; kinds {', '.join(c.kinds) or 'all'}; seed {c.seed}",
        f"markets: {result.candidates} selected, {result.with_price} with a price at "
        f"the cutoff, {result.common} forecast by every forecaster (scored)",
        f"runtime: {result.seconds:.1f} s",
        "",
        "| Forecaster | n | Brier | Log | Skill vs market | Reliability | Resolution "
        "| ECE | Cost USD |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in result.results:
        cal = r.calibration
        lines.append(
            f"| {r.name} | {r.n} | {r.brier:.4f} | {r.log:.4f} | {r.skill:+.4f} | "
            f"{cal.reliability:.4f} | {cal.resolution:.4f} | "
            f"{cal.expected_calibration_error:.4f} | {r.cost_usd:.2f} |"
        )
    lines += [
        "",
        f"Simulated bets from {c.initial_cash:.0f}, half-spread {c.half_spread}, "
        f"fee rate {c.fee_rate}, {c.kelly_multiplier} Kelly, cap {c.max_fraction:.0%} "
        f"per bet, minimum edge {c.min_edge}:",
        "",
        "| Forecaster | Bets | Return | Max drawdown | Win rate | Profit factor "
        "| Per-bet Sharpe | Sharpe 95% CI | P(Sharpe > 0) |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in result.results:
        if r.stats is None:
            continue
        s = r.stats
        ci = f"[{r.sharpe.lower:.3f}, {r.sharpe.upper:.3f}]" if r.sharpe else "n/a"
        positive = f"{r.sharpe.probability_positive:.2f}" if r.sharpe else "n/a"
        lines.append(
            f"| {r.name} | {s.count} | {s.total_return:+.2%} | {s.max_drawdown:.2%} | "
            f"{s.win_rate:.2%} | {s.profit_factor:.2f} | {s.per_bet_sharpe:.3f} | "
            f"{ci} | {positive} |"
        )
    return "\n".join(lines) + "\n"


def plots(
    result: BacktestResult,
    forecasts: dict[str, list[Forecast]],
    y: np.ndarray,
    reference: np.ndarray,
    out_dir: Path,
) -> None:
    """Reliability diagram, cumulative Brier advantage, equity curves."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], color="grey", linestyle="--", linewidth=1)
    for r in result.results:
        xs = [b.mean_forecast for b in r.calibration.bins]
        ys = [b.observed_frequency for b in r.calibration.bins]
        ax.plot(xs, ys, marker="o", label=f"{r.name} (n={r.n})")
    ax.set_xlabel("mean forecast")
    ax.set_ylabel("observed frequency")
    ax.set_title(f"Reliability, {result.config.domain}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "reliability.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for r in result.results:
        if r.name == "market":
            continue
        p = np.array([f.p_hat for f in forecasts[r.name]], dtype=float)
        advantage = np.cumsum(reference - scoring.brier(p, y))
        ax.plot(advantage, label=r.name)
    ax.axhline(0, color="grey", linewidth=1)
    ax.set_xlabel("markets in settlement order")
    ax.set_ylabel("cumulative Brier advantage over market")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "cumulative_score.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    for r in result.results:
        if r.bets:
            ax.plot(
                [result.config.initial_cash] + [b.bankroll_after for b in r.bets],
                label=f"{r.name} ({len(r.bets)} bets)",
            )
    ax.set_xlabel("bets in settlement order")
    ax.set_ylabel("bankroll")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "equity.png", dpi=120)
    plt.close(fig)
