"""Fill the archive from a point-in-time provider (docs/evidence.md).

``weather_runs`` finds every station a weather market in the root names,
records the stations, then reads each station's point-in-time forecasts
from the first market day (less ``lead_in`` days, for the error fit) to
yesterday, one capture per station. It resumes: a station whose captures
already reach a day is continued from the day after.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from vp.domains.weather import station
from vp.forecast.archive import Archive, write_capture
from vp.forecast.evidence import market_date
from vp.markets.schema import BinaryMarket
from vp.markets.store import read_markets
from vp.sources import open_meteo

logger = logging.getLogger(__name__)

FIRST = date(2024, 1, 1)  # the provider's archive starts here
CHUNK = timedelta(days=366)


def weather_markets(root: Path, domain: str | None = None) -> list[BinaryMarket]:
    """The temperature markets in the root: of ``domain``, or of every
    domain whose markets settle on an observation."""
    from vp.domains import DOMAINS

    names = [domain] if domain else [n for n, d in DOMAINS.items() if d.observes]
    markets = []
    for name in names:
        path = root / "markets" / name / "resolved.parquet"
        if path.exists():
            markets += read_markets(path)
        snaps = sorted((root / "snapshots" / name).glob("*.parquet"))
        if snaps:
            markets += read_markets(snaps[-1])
    return [m for m in markets if m.parsed.get("kind") == "daily_temperature"]


def station_days(markets: list[BinaryMarket]) -> dict[str, date]:
    """Each named station with the first market day it decides."""
    first: dict[str, date] = {}
    for m in markets:
        code, day = station(m.resolution_source), market_date(m)
        if code and day and (code not in first or day < first[code]):
            first[code] = day
    return first


def weather_runs(
    root: Path,
    domain: str | None = None,
    *,
    key: str | None = None,
    lead_in: int = 90,
    until: date | None = None,
    only: list[str] | None = None,
    say: Callable[[str], None] = print,
) -> dict[str, Any]:
    until = until or (datetime.now(tz=UTC).date() - timedelta(days=1))
    first = station_days(weather_markets(root, domain))
    if only:
        first = {k: v for k, v in first.items() if k in only}
    if not first:
        return {"stations": 0, "note": "no market names a station"}
    known = {
        r["station"]: r for r in Archive(root).rows("stations", datetime.now(tz=UTC))
    }
    missing = sorted(set(first) - set(known))
    if missing:
        found = open_meteo.stations(missing)
        write_capture(
            root,
            "stations",
            list(found.values()),
            provenance={"url": open_meteo.STATIONS, "ids": missing},
        )
        known.update(found)
    reached: dict[str, date] = {}
    for r in Archive(root).rows("open_meteo_runs", datetime.now(tz=UTC)):
        day = date.fromisoformat(r["day"])
        if r["station"] not in reached or day > reached[r["station"]]:
            reached[r["station"]] = day
    out: dict[str, Any] = {}
    for code in sorted(first):
        if code not in known:
            out[code] = "unknown station"
            continue
        start = max(FIRST, first[code] - timedelta(days=lead_in))
        if code in reached:
            start = max(start, reached[code] + timedelta(days=1))
        rows = 0
        while start <= until:
            end = min(until, start + CHUNK)
            try:
                got, request = open_meteo.previous_runs(
                    known[code], start, end, key=key
                )
            except Exception as exc:  # noqa: BLE001 - one station's failure is reported
                logger.warning("previous runs for %s failed: %s", code, exc)
                out[code] = f"stopped at {start}: {open_meteo.fetch_error(exc)}"
                break
            write_capture(root, "open_meteo_runs", got, provenance=request)
            rows += len(got)
            start = end + timedelta(days=1)
        else:
            out[code] = rows
        say(f"{code}: {out[code]}")
    return {"stations": len(first), "result": out}


def ensembles(
    root: Path, domain: str | None = None, *, key: str | None = None
) -> dict[str, Any]:
    """Capture the ensemble at every station an open market names."""
    today = datetime.now(tz=UTC).date()
    open_days = {
        code
        for m in weather_markets(root, domain)
        if (market_date(m) or today) >= today and not m.trading_closed
        if (code := station(m.resolution_source))
    }
    known = {
        r["station"]: r for r in Archive(root).rows("stations", datetime.now(tz=UTC))
    }
    rows: list[dict[str, Any]] = []
    requests = []
    for code in sorted(c for c in open_days if c in known):
        got, request = open_meteo.ensemble(known[code], key=key)
        rows += got
        requests.append(request)
    write_capture(root, "open_meteo_ensemble", rows, provenance={"requests": requests})
    return {"stations": len(requests), "rows": len(rows)}


def football(root: Path, seasons: list[str]) -> dict[str, Any]:
    """Read past and current seasons of every domain with an openfootball
    league into the archive; results are dated facts (docs/evidence.md)."""
    from vp.domains import DOMAINS
    from vp.sources import openfootball

    out: dict[str, Any] = {}
    for name, domain in DOMAINS.items():
        if not domain.openfootball:
            continue
        for season in seasons:
            try:
                data, request = openfootball.fetch(season, domain.openfootball)
            except Exception as exc:  # noqa: BLE001 - one season's failure is reported
                out[f"{name} {season}"] = type(exc).__name__
                continue
            got = openfootball.rows(data, name, domain.zone)
            write_capture(root, "openfootball", got, provenance=request)
            out[f"{name} {season}"] = len(got)
    return out


def recheck(
    root: Path, *, days: int = 30, key: str | None = None, tolerance: float = 0.05
) -> dict[str, Any]:
    """Read the last ``days`` of every archived station again and compare
    with what the archive holds: a point-in-time provider must return the
    same value for the same station, day and lead (docs/evidence.md)."""
    now = datetime.now(tz=UTC)
    held: dict[tuple[str, str, int], dict[str, Any]] = {}
    for r in Archive(root).rows("open_meteo_runs", now):
        held[(r["station"], r["day"], r["lead_days"])] = r
    sites = {r["station"]: r for r in Archive(root).rows("stations", now)}
    end = now.date() - timedelta(days=1)
    start = end - timedelta(days=days)
    compared = changed = 0
    examples: list[dict[str, Any]] = []
    failed: dict[str, str] = {}
    for code in sorted({s for s, _, _ in held}):
        if code not in sites:
            continue
        try:
            got, _ = open_meteo.previous_runs(sites[code], start, end, key=key)
        except Exception as exc:  # noqa: BLE001 - reported, the rest go on
            failed[code] = open_meteo.fetch_error(exc)
            continue
        for r in got:
            old = held.get((code, r["day"], r["lead_days"]))
            if old is None:
                continue
            compared += 1
            delta = max(abs(old["tmax"] - r["tmax"]), abs(old["tmin"] - r["tmin"]))
            if delta > tolerance:
                changed += 1
                if len(examples) < 5:
                    examples.append({"station": code, "day": r["day"], "delta": delta})
    return {
        "compared": compared,
        "changed": changed,
        "examples": examples,
        "failed": failed,
    }
