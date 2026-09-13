"""The backtest runner end to end on the temporary resolved set of test_forecast."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_forecast import root  # noqa: F401 - fixture
from vp.backtest.run import BacktestConfig, run_backtest, select_markets
from vp.markets.store import read_markets


def test_select_markets_filters_samples_and_orders(root: Path) -> None:  # noqa: F811
    resolved = read_markets(root / "markets" / "epl" / "resolved.parquet")
    config = BacktestConfig(domain="epl", kinds=("match",))
    rows = select_markets(resolved, config)
    assert [m.market_id for m in rows] == ["1", "2", "3", "4", "5", "6"]
    sampled = select_markets(
        resolved, BacktestConfig(domain="epl", max_markets=3, seed=1)
    )
    assert len(sampled) == 3
    assert sampled == sorted(sampled, key=lambda m: m.closed_time or "")


def test_run_backtest_scores_common_set_and_writes_outputs(root: Path) -> None:  # noqa: F811
    config = BacktestConfig(
        domain="epl",
        forecasters=("market", "constant", "elo"),
        hours_before_close=24.0,
        kinds=("match",),
        initial_cash=100.0,
    )
    out = root / "out"
    result = run_backtest(config, root, out, forecasters=None)
    # Only market 5 has a stored history, so it is the only market with a price
    # at the cutoff (2026-03-07T17:00Z reads the 2026-03-06 point, 0.90); Elo
    # declines it with min_games=3 by default, so the common set is empty.
    assert (result.candidates, result.with_price, result.common) == (6, 1, 0)
    assert (out / "summary.md").exists() and not (out / "reliability.png").exists()

    from vp.forecast.stats import Elo

    lenient = [
        __import__("vp.forecast.baselines", fromlist=["MarketPrice"]).MarketPrice(),
        __import__("vp.forecast.baselines", fromlist=["Constant"]).Constant(),
        Elo("epl", min_games=1),
    ]
    result = run_backtest(config, root, out, forecasters=lenient)
    assert result.common == 1
    names = {r.name: r for r in result.results}
    # The market's own price 0.90 on a market that resolved Yes.
    assert names["market"].brier == pytest.approx(0.01) and names["market"].skill == 0.0
    assert names["constant"].brier == pytest.approx(0.25)
    assert names["constant"].skill == pytest.approx(1 - 0.25 / 0.01)
    # Constant 0.5 against a 0.90 ask has edge on "no" and loses its stake.
    assert len(names["constant"].bets) == 1 and names["constant"].bets[0].pnl < 0
    assert names["constant"].stats is not None and names["constant"].stats.count == 1
    assert names["constant"].sharpe is None  # fewer than three bets
    assert names["market"].bets == []
    for name in (
        "reliability.png",
        "cumulative_score.png",
        "equity.png",
        "forecasts.jsonl",
    ):
        assert (out / name).exists()
    lines = [
        json.loads(line) for line in (out / "forecasts.jsonl").read_text().splitlines()
    ]
    assert sorted(row["forecaster"] for row in lines) == ["constant", "elo", "market"]
    assert "| constant | 1 | 0.2500 |" in (out / "summary.md").read_text()
