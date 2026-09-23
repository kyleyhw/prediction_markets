"""Signals and the benchmark on the platform: the bench job keeps the latest
result per domain; a week is frozen and sealed, shows only commitments
until it is revealed, and is scored from the venue's settlement records."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.conftest import needs_db
from tests.test_forecast import root  # noqa: F401 - fixture
from tests.test_platform_handlers import services  # noqa: F401 - fixture
from tests.test_strategy import make_market
from vp.markets.store import write_markets
from vp.platform import signals
from vp.platform.handlers import Services
from vp.signals import benchmark

pytestmark = needs_db
NOW = datetime(2026, 3, 2, 1, tzinfo=UTC)


def ctx(svc: Services, **payload) -> Any:
    return SimpleNamespace(
        services=svc, job=SimpleNamespace(payload=payload), progress=lambda *a: None
    )


def test_the_bench_job_keeps_the_latest_result_per_domain(
    app_pool,
    services: Services,  # noqa: F811
) -> None:
    out = signals.signal_bench(ctx(services, domain="epl"))
    assert "elo" in out["epl"]
    kept = signals.latest_bench(app_pool)["epl"]
    assert kept["domain"] == "epl" and "elo" in kept["signals"]


def test_a_week_is_sealed_until_it_is_revealed_and_then_scored(
    app_pool,
    pg_owner,
    services: Services,  # noqa: F811
    tmp_path: Path,
    monkeypatch,
) -> None:
    pg_owner.execute(
        "delete from benchmark_weeks where week = %s", (benchmark.week_of(NOW),)
    )
    open_markets = [
        make_market(
            market_id=f"b{i}",
            condition_id=f"0xb{i}",
            question=f"Will Arsenal FC win on 2026-03-0{i + 3}?",
            domain="epl",
            parsed={
                "kind": "match",
                "team_a": "Arsenal FC",
                "team_b": "Chelsea FC",
                "side": "Arsenal FC",
            },
            end_date=(NOW + timedelta(days=i + 1)).isoformat(),
            outcomes=(
                make_market().outcomes[0].__class__("Yes", None, 0.4 + 0.1 * i),
                make_market().outcomes[1],
            ),
        )
        for i in range(3)
    ]
    capture = tmp_path / "20260302T000000Z.parquet"
    write_markets(capture, open_markets)
    services.store.put_file(f"shared/snapshots/epl/{capture.name}", capture)
    frozen = signals.benchmark_freeze(ctx(services), now=NOW)
    assert frozen["questions"] == 3 and frozen["configs"] >= 1
    assert (
        signals.benchmark_freeze(ctx(services), now=NOW)["skipped"] == "already frozen"
    )
    (week,) = [
        w for w in signals.weeks(app_pool) if w["week"] == benchmark.week_of(NOW)
    ]
    assert week["seed"] == signals._seed(week["week"])
    market_entry = next(e for e in week["entries"] if e["config"] == "market")
    assert set(market_entry) == {"config", "commitment"}  # nothing else before reveal
    with pytest.raises(Exception, match="never changed"):
        pg_owner.execute(
            "update benchmark_entries set payload = 'x' where config = 'market'"
        )

    settled = {f"0xb{i}": i % 2 for i in range(3)}
    state = {"all_settled": False}

    def market(self, condition_id, depth=0):
        m = next(x for x in open_markets if x.condition_id == condition_id)
        if condition_id == "0xb2" and not state["all_settled"]:
            return replace(m, resolution_state="unresolved")
        return replace(
            m, resolution_state="resolved", resolved_outcome=settled[condition_id]
        )

    monkeypatch.setattr("vp.platform.handlers.ResolvedFirst.market", market)
    waiting = signals.benchmark_score(ctx(services), now=NOW + timedelta(days=2))
    assert waiting[week["week"]] == {"settled": 2, "of": 3}
    state["all_settled"] = True
    done = signals.benchmark_score(ctx(services), now=NOW + timedelta(days=4))
    assert done[week["week"]]["settled"] == 3
    (week,) = [
        w for w in signals.weeks(app_pool) if w["week"] == benchmark.week_of(NOW)
    ]
    revealed = next(e for e in week["entries"] if e["config"] == "market")
    payload = benchmark._canonical(
        {"week": week["hash"], "config": "market", "forecasts": revealed["forecasts"]}
    )
    assert benchmark.verify(revealed["commitment"], revealed["salt"], payload)
    assert revealed["score"]["n"] == 3 and revealed["score"]["ranked"] is False
    assert revealed["score"]["skill"] == pytest.approx(0.0)  # the market against itself
