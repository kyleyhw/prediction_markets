"""Football results from openfootball (CC0; docs/evidence.md, task 74).

A result is a dated fact: it is visible from kick-off plus three hours
(``available_at``), whenever it was fetched, so past seasons can be read
into the archive as they stood. A fixture not yet played has no
``available_at`` and is visible from its capture. Kick-off times in the
files are the league's local time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from vp.venues._http import throttled_get_json

URL = "https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{league}.json"
PLAYED = timedelta(hours=3)


def season_of(day: date) -> str:
    """The season a date falls in, August to July: "2026-27"."""
    start = day.year if day.month >= 8 else day.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def fetch(season: str, league: str) -> tuple[dict[str, Any], dict[str, Any]]:
    url = URL.format(season=season, league=league)
    return throttled_get_json(url, host_key="github_raw", min_interval=1.0), {
        "url": url
    }


def rows(data: dict[str, Any], domain: str, zone: str) -> list[dict[str, Any]]:
    """One row per match; a played one carries when its result was known."""
    out = []
    for m in data.get("matches") or []:
        # A score is {"ft": [..], "ht": [..]} or, in some files, the bare pair.
        score = m.get("score")
        ft = (score if isinstance(score, list) else (score or {}).get("ft")) or []
        row: dict[str, Any] = {
            "domain": domain,
            "season": data.get("name"),
            "round": m.get("round"),
            "date": m.get("date"),
            "time": m.get("time"),
            "team1": m.get("team1"),
            "team2": m.get("team2"),
            "goals1": ft[0] if len(ft) == 2 else None,
            "goals2": ft[1] if len(ft) == 2 else None,
        }
        if row["goals1"] is not None and m.get("date"):
            local = datetime.fromisoformat(f"{m['date']}T{m.get('time') or '23:59'}")
            kickoff = local.replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)
            row["available_at"] = (kickoff + PLAYED).isoformat()
        out.append(row)
    return out
