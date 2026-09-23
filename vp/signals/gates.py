"""The gates every signal passes before it is listed (task 63).

**Purity.** An AST scan of the signal's module: it may import only the
standard mathematics, numpy, typing and dataclass helpers, the date types
and the engine's own evidence, market and domain modules; it may not call
`open`, `eval`, `exec`, `compile`, `__import__`, `input` or the reflection
builtins, nor read a clock (`.now()`, `.today()`, `.utcnow()`). A signal
reads the world only through the evidence object it is handed, so what it
can see is what the cutoff allows.

**Cutoff sentinel.** A signal is computed on a synthetic data root (football
fixtures with results and exact scores, a series with maps, a city's daily
highs, price histories) at a cutoff, and again after sentinel rows are
added after the cutoff: later results and scores that reverse every
strength, later days far outside the season, later prices at the extremes.
Every value must be identical. The same comparison says that moving the
cutoff later never changes a value computed at an earlier one.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from vp.domains import DOMAINS
from vp.forecast.archive import write_capture
from vp.forecast.evidence import Evidence
from vp.markets.schema import BinaryMarket, Outcome
from vp.markets.store import write_history, write_markets
from vp.signals.base import Signal

ALLOWED_IMPORTS = (
    "__future__",
    "math",
    "statistics",
    "numpy",
    "dataclasses",
    "typing",
    "collections",
    "bisect",
    "datetime",
    "vp.signals",
    "vp.forecast.evidence",
    "vp.forecast.base",
    "vp.forecast.baselines",
    "vp.forecast.stats",
    "vp.markets.schema",
    "vp.domains",
)
BANNED_CALLS = {
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "setattr",
    "delattr",
    "breakpoint",
}
BANNED_ATTRIBUTES = {"now", "today", "utcnow"}


def purity(signal: Signal) -> list[str]:
    """What in the signal's module breaks the purity rule; empty if nothing."""
    module = inspect.getmodule(type(signal))
    if module is None:
        return ["the signal has no module to scan"]
    tree = ast.parse(inspect.getsource(module))
    problems = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            assert isinstance(node, ast.Import | ast.ImportFrom)
            if not any(
                name == ok or name.startswith(ok + ".") for ok in ALLOWED_IMPORTS
            ):
                problems.append(f"line {node.lineno}: imports {name}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                problems.append(f"line {node.lineno}: calls {node.func.id}")
        if isinstance(node, ast.Attribute) and node.attr in BANNED_ATTRIBUTES:
            problems.append(f"line {node.lineno}: reads the clock (.{node.attr})")
    return problems


def metadata(signal: Signal) -> list[str]:
    """What the contribution checklist finds missing from the metadata."""
    meta = signal.meta
    problems = [
        f"no {name}"
        for name in ("id", "title", "cutoff", "warmup", "licence")
        if not str(getattr(meta, name)).strip()
    ]
    if not meta.references:
        problems.append("no reference for the method")
    if not meta.accessors and not meta.uses_price:
        problems.append("names no evidence accessor")
    return problems


# ------------------------------------------------------------------ fixtures

CUTOFF = datetime(2026, 3, 1, tzinfo=UTC)
STATION_URL = "https://www.weather.gov/wrh/timeseries?site=ktst"
TEAMS = ("Alpha FC", "Bravo FC", "Charlie FC", "Delta FC")


def _market(**fields: Any) -> BinaryMarket:
    base: dict[str, Any] = dict(
        market_id="m",
        condition_id=None,
        slug=None,
        question="?",
        event_id=None,
        event_title=None,
        domain=None,
        status="resolved",
        trading_closed=True,
        resolution_state="resolved",
        winning_outcome=None,
        resolved_outcome=None,
        end_date=None,
        closed_time=None,
        outcomes=(Outcome("Yes", None, None), Outcome("No", None, None)),
        best_bid=None,
        best_ask=None,
        spread=None,
        last_trade_price=None,
        volume_usd=None,
        liquidity_usd=None,
        tags=(),
        fetched_at="2026-03-01T00:00:00Z",
    )
    return BinaryMarket(**{**base, **fields})


@dataclass
class Fixture:
    root: Path
    targets: list[BinaryMarket]


def _domain_with(test: Any) -> str:
    return next(name for name, d in DOMAINS.items() if test(d))


def build(root: Path, *, sentinel: bool = False) -> Fixture:
    """A synthetic data root; with ``sentinel``, rows after the cutoff that
    would move every estimate were they read."""
    football = _domain_with(lambda d: d.home_first)
    series = _domain_with(lambda d: "match" in d.kinds and not d.home_first)
    weather = _domain_with(lambda d: "daily_temperature" in d.kinds)
    per_domain: dict[str, list[BinaryMarket]] = {football: [], series: [], weather: []}
    targets: list[BinaryMarket] = []
    n = 0

    def add(domain: str, **fields: Any) -> BinaryMarket:
        nonlocal n
        n += 1
        m = _market(market_id=f"{domain}{n}", domain=domain, **fields)
        per_domain[domain].append(m)
        return m

    # Football: every pair twice before the cutoff, the stronger listed team
    # (lower index) scoring more; the sentinel reverses it after the cutoff.
    rounds = [(a, b) for a in TEAMS for b in TEAMS if a != b]
    for k, (a, b) in enumerate(rounds):
        for later in (False, True):
            if later and not sentinel:
                continue
            when = (
                CUTOFF + timedelta(days=k + 1)
                if later
                else CUTOFF - timedelta(days=60 - 2 * k)
            )
            strong = TEAMS.index(a) < TEAMS.index(b)
            ga, gb = (
                ((2, 1) if strong else (0, 1))
                if not later
                else ((0, 9) if strong else (9, 0))
            )
            event = f"{a} vs. {b}"
            iso = when.isoformat()
            winner = a if ga > gb else (b if gb > ga else "draw")
            for side in (a, b, "draw"):
                question = (
                    f"Will {a} vs. {b} end in a draw?"
                    if side == "draw"
                    else f"Will {side} win on {iso[:10]}?"
                )
                add(
                    football,
                    question=question,
                    event_id=event,
                    event_title=event,
                    closed_time=iso,
                    resolved_outcome=int(winner == side),
                    parsed={"kind": "match", "team_a": a, "team_b": b, "side": side},
                )
            for score in ((ga, gb), (1, 1)):
                if score == (ga, gb) or (1, 1) != (ga, gb):
                    add(
                        football,
                        question=f"Exact Score: {a} {score[0]} - {score[1]} {b}?",
                        event_id=event + " - Exact Score",
                        event_title=event + " - Exact Score",
                        closed_time=iso,
                        resolved_outcome=int(score == (ga, gb)),
                        parsed={
                            "kind": "exact_score",
                            "team_a": a,
                            "team_b": b,
                            "period": "full",
                            "score": f"{score[0]}-{score[1]}",
                        },
                    )
    target_time = (CUTOFF + timedelta(days=30)).isoformat()
    a, b = TEAMS[0], TEAMS[3]
    for fields in (
        {"kind": "match", "team_a": a, "team_b": b, "side": a},
        {"kind": "match", "team_a": a, "team_b": b, "side": "draw"},
        {
            "kind": "total",
            "team_a": a,
            "team_b": b,
            "period": "full",
            "stat": "goals",
            "line": "2.5",
        },
        {"kind": "both_teams_to_score", "team_a": a, "team_b": b, "period": "full"},
        {
            "kind": "exact_score",
            "team_a": a,
            "team_b": b,
            "period": "full",
            "score": "2-1",
        },
        {
            "kind": "spread",
            "team_a": a,
            "team_b": b,
            "period": "full",
            "stat": "goals",
            "line": "-1.5",
            "team": a,
        },
    ):
        targets.append(
            _market(
                market_id=f"t{len(targets)}",
                domain=football,
                event_id="target",
                end_date=target_time,
                closed_time=target_time,
                parsed=fields,
                status="active",
                trading_closed=False,
                resolution_state="unresolved",
            )
        )
    # A series domain with maps.
    for k in range(12):
        for later in (False, True):
            if later and not sentinel:
                continue
            when = (
                CUTOFF + timedelta(days=k + 1)
                if later
                else CUTOFF - timedelta(days=30 - k)
            )
            a, b = TEAMS[k % 4], TEAMS[(k + 1) % 4]
            first_wins = (TEAMS.index(a) < TEAMS.index(b)) != later
            for fields in ({}, {"map": "1"}):
                add(
                    series,
                    question=f"{a} vs {b}",
                    event_id=f"s{k}{later}",
                    closed_time=when.isoformat(),
                    resolved_outcome=int(first_wins),
                    outcomes=(Outcome(a, None, None), Outcome(b, None, None)),
                    parsed={"kind": "match", "team_a": a, "team_b": b, **fields},
                )
    for fields in ({}, {"map": "1"}):
        targets.append(
            _market(
                market_id=f"t{len(targets)}",
                domain=series,
                outcomes=(Outcome(TEAMS[0], None, None), Outcome(TEAMS[1], None, None)),
                end_date=target_time,
                status="active",
                trading_closed=False,
                resolution_state="unresolved",
                parsed={
                    "kind": "match",
                    "team_a": TEAMS[0],
                    "team_b": TEAMS[1],
                    **fields,
                },
            )
        )
    # Weather: 250 days of highs around 20 degrees before the cutoff (enough
    # for the calibrations' 200 settled markets); the sentinel adds later
    # days at 40.
    months = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    for k in range(280):
        day = (CUTOFF - timedelta(days=250)).date() + timedelta(days=k)
        later = day >= CUTOFF.date()
        if later and not sentinel:
            continue
        value = 40 if later else 18 + k % 5
        label = f"{months[day.month - 1]} {day.day}"
        end = datetime(day.year, day.month, day.day, 23, tzinfo=UTC).isoformat()
        add(
            weather,
            question=f"Will the highest temperature in Testville be {value}°C "
            f"on {label}?",
            event_id=f"w{day}",
            end_date=end,
            closed_time=end,
            resolved_outcome=1,
            resolution_source=STATION_URL,
            parsed={
                "kind": "daily_temperature",
                "statistic": "highest",
                "city": "Testville",
                "date": label,
                "low": str(value),
                "high": str(value),
                "unit": "°C",
            },
        )
    target_day = CUTOFF.date() + timedelta(days=1)
    target_end = datetime(
        target_day.year, target_day.month, target_day.day, 23, tzinfo=UTC
    ).isoformat()
    for low, high in (("", "17"), ("18", "19"), ("20", "21"), ("22", "")):
        targets.append(
            _market(
                market_id=f"t{len(targets)}",
                domain=weather,
                event_id="wtarget",
                end_date=target_end,
                resolution_source=STATION_URL,
                status="active",
                trading_closed=False,
                resolution_state="unresolved",
                parsed={
                    "kind": "daily_temperature",
                    "statistic": "highest",
                    "city": "Testville",
                    "date": f"March {target_day.day}",
                    "low": low,
                    "high": high,
                    "unit": "°C",
                },
            )
        )
    for domain, markets in per_domain.items():
        write_markets(
            root / "markets" / domain / "resolved.parquet",
            markets + [t for t in targets if t.domain == domain],
        )
    # Prices: every market has a path before its settlement; the sentinel
    # appends points after the cutoff at the extremes.
    for m in [*per_domain[football], *per_domain[weather], *targets]:
        settle = datetime.fromisoformat(
            (m.closed_time or m.end_date or target_time).replace("Z", "+00:00")
        )
        start = min(settle, CUTOFF) - timedelta(days=5)
        points = [
            {
                "timestamp": (start + timedelta(hours=12 * i)).isoformat(),
                "implied_probability": round(0.3 + 0.05 * (i % 5), 3),
            }
            for i in range(10)
            if start + timedelta(hours=12 * i) <= min(settle, CUTOFF)
        ]
        if sentinel:
            points += [
                {
                    "timestamp": (CUTOFF + timedelta(hours=h)).isoformat(),
                    "implied_probability": 0.99,
                }
                for h in (1, 2)
            ]
        write_history(
            root / "histories" / (m.domain or "") / f"{m.market_id}.parquet",
            market_id=m.market_id,
            clob_token_id=None,
            outcome="Yes",
            points=points,
        )
    _archive(root, weather, sentinel)
    return Fixture(root, targets)


def _archive(root: Path, weather: str, sentinel: bool) -> None:
    """Archive captures: forecasts one degree below each observed day, as
    their provider issued them; an ensemble and headlines captured just
    before the cutoff. The sentinel adds forecasts and an ensemble at 40
    degrees, and headlines, that became visible only after it."""
    first = (CUTOFF - timedelta(days=250)).date()
    runs = []
    for k in range(252):
        day = first + timedelta(days=k)
        last = datetime(day.year, day.month, day.day, 23, tzinfo=UTC)
        for lead in (1, 2, 3):
            runs.append(
                {
                    "station": "KTST",
                    "day": day.isoformat(),
                    "lead_days": lead,
                    "tmax": float(18 + k % 5 - 1) if day < CUTOFF.date() else 19.0,
                    "tmin": 5.0,
                    "available_at": (last - timedelta(days=lead, hours=-6)).isoformat(),
                }
            )
    if sentinel:
        runs += [
            {
                "station": "KTST",
                "day": (CUTOFF.date() + timedelta(days=d)).isoformat(),
                "lead_days": 0,
                "tmax": 40.0,
                "tmin": 30.0,
                "available_at": (CUTOFF + timedelta(hours=d)).isoformat(),
            }
            for d in (1, 2)
        ]
    write_capture(
        root, "open_meteo_runs", runs, provenance={}, now=CUTOFF + timedelta(days=30)
    )
    target = (CUTOFF.date() + timedelta(days=1)).isoformat()
    for when, value in ((CUTOFF - timedelta(hours=2), 20.0),) + (
        ((CUTOFF + timedelta(hours=1), 40.0),) if sentinel else ()
    ):
        members = [
            {
                "station": "KTST",
                "day": target,
                "member": i,
                "tmax": value + i % 3,
                "tmin": 5.0,
            }
            for i in range(20)
        ]
        write_capture(root, "open_meteo_ensemble", members, provenance={}, now=when)
        write_capture(
            root,
            "gdelt",
            [
                {
                    "domain": weather,
                    "title": f"Heat at {value}",
                    "url": "u",
                    "source": "s",
                }
            ],
            provenance={},
            now=when,
        )


def fixtures(workdir: Path) -> tuple[Fixture, Fixture]:
    """The plain fixture root and the one with sentinel rows, built once."""
    return build(workdir / "plain"), build(workdir / "sentinel", sentinel=True)


def cutoff_sentinel(make: Any, plain: Fixture, guarded: Fixture) -> list[str]:
    """Where ``make()``'s values move when rows after the cutoff exist;
    empty if nowhere. ``make`` builds a fresh signal each time."""
    problems = []
    answered = 0
    for target in plain.targets:
        a, b = make(), make()
        if not a.meta.applies(target):
            continue
        x = a.compute(target, Evidence(CUTOFF, plain.root))
        y = b.compute(target, Evidence(CUTOFF, guarded.root))
        answered += x is not None
        if x != y:
            problems.append(f"{target.parsed}: {x} without, {y} with later rows")
    if not answered:
        problems.append("answered no fixture market, so the gate says nothing")
    return problems
