"""Forecasters against a small resolved set written to a temporary data root.

The set is built from the record shapes the dataset writes, with settlement
times chosen so that a cutoff between two rounds of matches includes the
first round and excludes the second: every test of the cutoff is a test that
the second round is invisible.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from vp.forecast.base import P_FLOOR, Forecast, clip
from vp.forecast.baselines import Climatology, Constant, MarketPrice
from vp.forecast.evidence import Evidence, market_date, parse_time
from vp.forecast.registry import Registry
from vp.forecast.stats import Elo, fit_elo
from vp.markets.schema import BinaryMarket, Outcome
from vp.markets.store import write_history, write_markets


def market(
    market_id: str,
    question: str,
    *,
    domain: str,
    parsed: dict[str, str],
    label: int | None,
    closed: str,
    end: str | None = None,
    outcomes: tuple[str, str] = ("Yes", "No"),
    title: str | None = None,
) -> BinaryMarket:
    return BinaryMarket(
        market_id=market_id,
        condition_id=None,
        slug=None,
        question=question,
        event_id=None,
        event_title=title,
        domain=domain,
        status="resolved",
        trading_closed=True,
        resolution_state="resolved",
        winning_outcome=outcomes[0] if label == 1 else outcomes[1],
        resolved_outcome=label,
        end_date=end or closed,
        closed_time=closed,
        outcomes=(
            Outcome(outcomes[0], f"{market_id}0", 0.5),
            Outcome(outcomes[1], f"{market_id}1", 0.5),
        ),
        best_bid=None,
        best_ask=None,
        spread=None,
        last_trade_price=None,
        volume_usd=None,
        liquidity_usd=None,
        tags=(),
        fetched_at="2026-09-13T00:00:00Z",
        parsed=parsed,
    )


def epl_match(
    mid: str, a: str, b: str, side: str, label: int, closed: str
) -> BinaryMarket:
    q = (
        f"Will {side} win on {closed[:10]}?"
        if side != "draw"
        else f"Will {a} vs. {b} end in a draw?"
    )
    return market(
        mid,
        q,
        domain="epl",
        parsed={"kind": "match", "team_a": a, "team_b": b, "side": side},
        label=label,
        closed=closed,
        title=f"{a} vs. {b}",
    )


def weather(
    mid: str, city: str, day: str, low: str, high: str, label: int
) -> BinaryMarket:
    d = date.fromisoformat(day)
    return market(
        mid,
        f"Will the highest temperature in {city} be {low}-{high}°C on {d:%B} {d.day}?",
        domain="weather",
        parsed={
            "kind": "daily_temperature",
            "statistic": "highest",
            "city": city,
            "date": f"{d:%B} {d.day}",
            "low": low,
            "high": high,
            "unit": "°C",
        },
        label=label,
        closed=f"{day}T12:00:00Z",
    )


# Round one settles on 2026-03-01, round two on 2026-03-08; the cutoff sits between.
ROUND_ONE = "2026-03-01T17:00:00Z"
ROUND_TWO = "2026-03-08T17:00:00Z"
CUTOFF = datetime(2026, 3, 5, tzinfo=timezone.utc)

EPL = [
    epl_match("1", "Arsenal FC", "Chelsea FC", "Arsenal FC", 1, ROUND_ONE),
    epl_match("2", "Arsenal FC", "Chelsea FC", "Chelsea FC", 0, ROUND_ONE),
    epl_match("3", "Arsenal FC", "Chelsea FC", "draw", 0, ROUND_ONE),
    epl_match("4", "Leeds United", "Everton FC", "draw", 1, ROUND_ONE),
    epl_match("5", "Chelsea FC", "Arsenal FC", "Chelsea FC", 1, ROUND_TWO),
    epl_match("6", "Chelsea FC", "Leeds United", "Chelsea FC", 1, ROUND_TWO),
]
WEATHER = [
    weather("w1", "London", "2025-03-03", "10", "11", 1),
    weather("w2", "London", "2025-03-04", "12", "13", 1),
    weather("w3", "London", "2025-03-05", "10", "11", 1),
    weather("w4", "London", "2025-03-06", "10", "11", 1),
    weather("w5", "London", "2025-03-07", "14", "15", 1),
    weather("w6", "London", "2025-03-07", "10", "11", 0),
    weather("w7", "London", "2026-03-07", "10", "11", 1),
]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", EPL)
    write_markets(tmp_path / "markets" / "weather" / "resolved.parquet", WEATHER)
    write_history(
        tmp_path / "histories" / "epl" / "5.parquet",
        market_id="5",
        clob_token_id="50",
        outcome="Yes",
        points=[
            {"timestamp": "2026-03-04T00:00:00Z", "implied_probability": 0.40},
            {"timestamp": "2026-03-05T00:00:00Z", "implied_probability": 0.45},
            {"timestamp": "2026-03-06T00:00:00Z", "implied_probability": 0.90},
        ],
        bar_minutes=1440,
    )
    return tmp_path


def test_time_parsing_and_market_date() -> None:
    assert parse_time("2024-05-19 20:09:58+00") == datetime(
        2024, 5, 19, 20, 9, 58, tzinfo=timezone.utc
    )
    assert parse_time("2026-09-12T12:00:00Z") == datetime(
        2026, 9, 12, 12, tzinfo=timezone.utc
    )
    assert parse_time(None) is None and parse_time("garbage") is None
    assert market_date(WEATHER[0]) == date(2025, 3, 3)


def test_evidence_results_stop_at_the_cutoff(root: Path) -> None:
    ev = Evidence(CUTOFF, root)
    results = ev.results("epl")
    # Round one only: the side that won names the winner once, the draw once.
    # Names are canonical: the club suffix is dropped and case folded.
    assert [(r.team_a, r.team_b, r.winner) for r in results] == [
        ("arsenal", "chelsea", "arsenal"),
        ("leeds united", "everton", "draw"),
    ]
    later = Evidence(datetime(2026, 3, 9, tzinfo=timezone.utc), root)
    assert len(later.results("epl")) == 4
    with pytest.raises(ValueError):
        Evidence(datetime(2026, 3, 5), root)


def test_evidence_price_at_cutoff(root: Path) -> None:
    ev = Evidence(CUTOFF, root)
    # The point stamped exactly at the cutoff is included; the later one is not.
    assert ev.price_at(EPL[4]) == 0.45
    assert ev.price_at(EPL[0]) is None
    assert MarketPrice().forecast(EPL[4], ev) == Forecast(
        "5", "market", CUTOFF.isoformat(), 0.45, "market price at cutoff: 0.450"
    )
    assert MarketPrice().forecast(EPL[0], ev) is None


def test_constant_and_clip(root: Path) -> None:
    ev = Evidence(CUTOFF, root)
    f = Constant(0.0).forecast(EPL[0], ev)
    assert f is not None and f.p_hat == P_FLOOR
    assert clip(2.0) == 1 - P_FLOOR


def test_elo_uses_only_pre_cutoff_results(root: Path) -> None:
    ratings, draw_rate = fit_elo(Evidence(CUTOFF, root).results("epl"), k=32)
    assert ratings["arsenal"] == pytest.approx(1516.0) and ratings[
        "chelsea"
    ] == pytest.approx(1484.0)
    assert draw_rate == 0.5
    elo = Elo("epl", min_games=1)
    f = elo.forecast(EPL[4], Evidence(CUTOFF, root))  # Chelsea to win round two
    assert f is not None
    expected_chelsea = 1 / (1 + 10 ** ((1516 - 1484) / 400))
    assert f.p_hat == pytest.approx(expected_chelsea - draw_rate / 2)
    draw = elo.forecast(EPL[2], Evidence(CUTOFF, root))
    assert draw is not None and draw.p_hat == 0.5
    assert Elo("epl").forecast(EPL[4], Evidence(CUTOFF, root)) is None  # min_games=3
    assert elo.forecast(WEATHER[0], Evidence(CUTOFF, root)) is None


def test_climatology_from_realised_buckets(root: Path) -> None:
    ev = Evidence(datetime(2026, 3, 6, tzinfo=timezone.utc), root)
    obs = ev.daily_highs("London")
    # 2025 has five days (one bucket each; w6 resolved No and is not an observation);
    # the 2026-03-07 day is after the cutoff.
    assert [o.day.isoformat() for o in obs] == [f"2025-03-0{d}" for d in range(3, 8)]
    target = weather("t", "London", "2026-03-07", "10", "11", 0)
    f = Climatology(min_obs=3).forecast(target, ev)
    # Three of five earlier-year observations fall in [10, 11]; Laplace gives 4/7.
    assert f is not None and f.p_hat == pytest.approx(4 / 7)
    assert Climatology(min_obs=6).forecast(target, ev) is None
    assert Climatology().forecast(EPL[0], ev) is None


def test_registry_round_trip(tmp_path: Path) -> None:
    reg = Registry(tmp_path / "r" / "forecasts.jsonl")
    f = Forecast("1", "elo", CUTOFF.isoformat(), 0.6, "why", 0.01, {"k": "v"})
    reg.append(f)
    reg.append(f)
    assert list(reg.read()) == [f, f]
    line = (tmp_path / "r" / "forecasts.jsonl").read_text().splitlines()[0]
    assert '"rationale_sha256"' in line
