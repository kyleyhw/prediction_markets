"""Weather evidence at the stations markets resolve on (docs/evidence.md,
task 73).

* :func:`stations` reads each ICAO code's coordinates from the Aviation
  Weather Center (public domain).
* :func:`previous_runs` turns Open-Meteo's Previous Runs API into one row
  per station, local day and lead: the day's maximum and minimum of the
  hourly 2 m temperature "predicted N×24 hours before valid time", with
  ``available_at`` the last hour of the day minus N days plus six hours for
  the run's delivery, the latest moment the value can have existed.
* :func:`ensemble` turns the Ensemble API into one row per station, day and
  member, visible from its capture only.

With a key the paid hosts are used (``customer-`` prefix, ``apikey``);
without one the free hosts, which answer 429 when the address is over its
limit, so each request is retried with a growing pause.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from vp.venues._http import throttled_get

STATIONS = "https://aviationweather.gov/api/data/stationinfo"
DELIVERY = timedelta(hours=6)
MIN_HOURS = 20
PAUSES = (10, 30, 60, 120)


def _url(api: str, path: str, key: str | None) -> str:
    return f"https://{'customer-' if key else ''}{api}.open-meteo.com/v1/{path}"


def get(url: str, params: dict[str, Any], host: str) -> Any:
    """GET JSON, pausing and retrying while the provider answers 429."""
    for pause in (*PAUSES, None):
        response = throttled_get(
            url, host_key=host, min_interval=1.0, params=params, timeout=60
        )
        if response.status_code != 429 or pause is None:
            response.raise_for_status()
            return response.json()
        time.sleep(pause)
    raise AssertionError("unreachable")


def stations(codes: list[str]) -> dict[str, dict[str, Any]]:
    """Coordinates, elevation and country of each ICAO code that is known."""
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(codes), 50):
        batch = ",".join(codes[i : i + 50])
        for s in get(STATIONS, {"ids": batch, "format": "json"}, "aviationweather"):
            out[s["icaoId"]] = {
                "station": s["icaoId"],
                "name": s.get("site"),
                "latitude": s["lat"],
                "longitude": s["lon"],
                "elevation": s.get("elev"),
                "country": s.get("country"),
            }
    return out


def previous_runs(
    station: dict[str, Any],
    start: date,
    end: date,
    *,
    leads: tuple[int, ...] = (1, 2),
    key: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rows of daily extremes by lead for one station, and the request made."""
    params: dict[str, Any] = {
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "hourly": ",".join(f"temperature_2m_previous_day{n}" for n in leads),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "auto",
    }
    request = {"url": _url("previous-runs-api", "forecast", None), **params}
    data = get(
        _url("previous-runs-api", "forecast", key),
        params | ({"apikey": key} if key else {}),
        "open_meteo",
    )
    return daily_rows(station, data, leads), request


def daily_rows(
    station: dict[str, Any], data: dict[str, Any], leads: tuple[int, ...]
) -> list[dict[str, Any]]:
    """Group an hourly answer (local wall-clock times) into local days."""
    zone = ZoneInfo(data["timezone"])
    hourly = data.get("hourly") or {}
    times = [datetime.fromisoformat(t) for t in hourly.get("time") or []]
    rows = []
    for n in leads:
        values = hourly.get(f"temperature_2m_previous_day{n}") or []
        by_day: dict[date, list[tuple[datetime, float]]] = {}
        for t, v in zip(times, values, strict=False):
            if v is not None:
                by_day.setdefault(t.date(), []).append((t, float(v)))
        for day, points in sorted(by_day.items()):
            if len(points) < MIN_HOURS:
                continue
            last = max(t for t, _ in points).replace(tzinfo=zone).astimezone(UTC)
            rows.append(
                {
                    "station": station["station"],
                    "latitude": station["latitude"],
                    "longitude": station["longitude"],
                    "timezone": data["timezone"],
                    "day": day.isoformat(),
                    "lead_days": n,
                    "model": "best_match",
                    "tmax": max(v for _, v in points),
                    "tmin": min(v for _, v in points),
                    "available_at": (last - timedelta(days=n) + DELIVERY).isoformat(),
                }
            )
    return rows


def ensemble(
    station: dict[str, Any], *, days: int = 7, key: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One row per day and member of the ECMWF ensemble at the station."""
    params: dict[str, Any] = {
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "daily": "temperature_2m_max,temperature_2m_min",
        "models": "ecmwf_ifs025",
        "forecast_days": days,
        "timezone": "auto",
    }
    request = {"url": _url("ensemble-api", "ensemble", None), **params}
    data = get(
        _url("ensemble-api", "ensemble", key),
        params | ({"apikey": key} if key else {}),
        "open_meteo",
    )
    daily = data.get("daily") or {}
    members = sorted(
        k.removeprefix("temperature_2m_max")
        for k in daily
        if k.startswith("temperature_2m_max")
    )
    rows = []
    for i, day in enumerate(daily.get("time") or []):
        for suffix in members:
            tmax = daily[f"temperature_2m_max{suffix}"][i]
            tmin = (daily.get(f"temperature_2m_min{suffix}") or [None] * (i + 1))[i]
            if tmax is None:
                continue
            rows.append(
                {
                    "station": station["station"],
                    "day": day,
                    "member": int(suffix.removeprefix("_member") or 0),
                    "tmax": float(tmax),
                    "tmin": None if tmin is None else float(tmin),
                }
            )
    return rows, request


def fetch_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__
