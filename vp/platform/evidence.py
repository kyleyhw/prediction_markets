"""The evidence archive's collectors (plan, task 33).

Evidence indexed by time only accumulates forward: a forecast issued this
morning cannot be downloaded next year as it stood this morning, so a
backtest can use it honestly only if it was captured then. The collectors
start now; the readers that give forecasters this evidence behind the
cutoff come in Phase 17.

Each collector writes one Parquet file per run to
`shared/evidence/<source>/<YYYY-MM-DD>/<stamp>.parquet`, every row carrying
`captured_at`, and records the file in `evidence_captures`. The sources and
their terms (flag F9) are in `docs/evidence.md`; in short:

* `open_meteo`: daily high and low forecasts for every city the weather
  markets name, all cities in one request; free for non-commercial use,
  so production needs the paid plan before launch.
* `openfootball`: Premier League fixtures and results from the
  openfootball project, public domain (CC0).
* `venue_schedules`: the questions, events and closing times the venue
  itself lists for every tracked market, from our own registry.
* `gdelt`: a headline set per domain from the GDELT DOC API, free and open
  with attribution, at most one request every five seconds.

A source that fails does not stop the others; the job's result lists each.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from vp.domains import DOMAINS, Domain
from vp.markets.schema import utc_now_iso
from vp.platform.jobs import JobContext
from vp.platform.storage import SHARED, ObjectStore
from vp.venues._http import set_rate, throttled_get_json

logger = logging.getLogger(__name__)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
OPENFOOTBALL = (
    "https://raw.githubusercontent.com/openfootball/football.json/master/"
    "{season}/en.1.json"
)
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"


def headline_query(domain: Domain) -> str:
    """What GDELT is asked about a domain: its first few keywords, quoted."""
    words = [k.strip() for k in domain.keywords if len(k.strip()) > 3][:4]
    return " OR ".join(f'"{w}"' for w in words)


GEOCODE_KEY = f"{SHARED}/evidence/geocode.json"

set_rate("gdelt", rate=0.2, burst=1)
set_rate("open_meteo", rate=5.0, burst=10)


def _get(url: str, host: str, params: dict[str, Any] | None = None) -> Any:
    return throttled_get_json(
        url, host_key=host, min_interval=0.0, params=params, timeout=30
    )


def _store(
    store: ObjectStore,
    pool: Any,
    source: str,
    domain: str | None,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write one capture and index it; returns what was written."""
    if not rows:
        return {"rows": 0}
    now = datetime.now(tz=UTC)
    stamp = utc_now_iso().replace("-", "").replace(":", "")
    key = f"{SHARED}/evidence/{source}/{now:%Y-%m-%d}/{stamp}.parquet"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "capture.parquet"
        pq.write_table(pa.Table.from_pylist(rows), path)
        size = path.stat().st_size
        store.put_file(key, path)
    with pool.connection() as conn:
        conn.execute(
            "insert into evidence_captures (source, domain, subject, captured_at, "
            "object_key, rows, bytes) values (%s, %s, %s, %s, %s, %s, %s)",
            (source, domain, source, now, key, len(rows), size),
        )
    return {"rows": len(rows), "key": key}


# -------------------------------------------------------------- the sources


def weather_cities(pool: Any) -> list[str]:
    """Cities the open weather markets name, from the market registry."""
    with pool.connection() as conn:
        rows = conn.execute(
            "select distinct p.value ->> 1 from tracked_markets t, "
            "jsonb_array_elements(t.record -> 'parsed') p "
            "where t.domain = 'weather' and not t.closed and p.value ->> 0 = 'city'"
        ).fetchall()
    return sorted(r[0] for r in rows if r[0])


def geocode(store: ObjectStore, cities: list[str]) -> dict[str, dict[str, Any]]:
    """Coordinates for each city, cached in the store (places do not move)."""
    raw = store.get_bytes(GEOCODE_KEY)
    known: dict[str, dict[str, Any]] = json.loads(raw) if raw else {}
    changed = False
    for city in cities:
        if city in known:
            continue
        found = _get(GEOCODE, "open_meteo_geocode", {"name": city, "count": 1})
        results = found.get("results") if isinstance(found, dict) else None
        if results:
            r = results[0]
            known[city] = {
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "timezone": r.get("timezone"),
                "country": r.get("country_code"),
            }
            changed = True
    if changed:
        store.put_bytes(GEOCODE_KEY, json.dumps(known, sort_keys=True).encode())
    return {c: known[c] for c in cities if c in known}


def open_meteo(store: ObjectStore, pool: Any) -> dict[str, Any]:
    places = geocode(store, weather_cities(pool))
    if not places:
        return {"rows": 0, "note": "no weather cities tracked yet"}
    names = sorted(places)
    payload = _get(
        OPEN_METEO,
        "open_meteo",
        {
            "latitude": ",".join(str(places[c]["latitude"]) for c in names),
            "longitude": ",".join(str(places[c]["longitude"]) for c in names),
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": 16,
        },
    )
    answers = payload if isinstance(payload, list) else [payload]
    captured = utc_now_iso()
    rows = []
    for city, answer in zip(names, answers, strict=False):
        daily = answer.get("daily") or {}
        for i, day in enumerate(daily.get("time") or []):
            rows.append(
                {
                    "captured_at": captured,
                    "city": city,
                    "latitude": answer.get("latitude"),
                    "longitude": answer.get("longitude"),
                    "timezone": answer.get("timezone"),
                    "date": day,
                    "lead_days": i,
                    "temperature_2m_max": _at(daily.get("temperature_2m_max"), i),
                    "temperature_2m_min": _at(daily.get("temperature_2m_min"), i),
                }
            )
    return _store(store, pool, "open_meteo", "weather", rows)


def _at(values: list[Any] | None, i: int) -> Any:
    return values[i] if values and i < len(values) else None


def season(now: datetime) -> str:
    """The football season a date falls in: August to July, "2026-27"."""
    start = now.year if now.month >= 8 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def openfootball(store: ObjectStore, pool: Any) -> dict[str, Any]:
    now = datetime.now(tz=UTC)
    data = _get(OPENFOOTBALL.format(season=season(now)), "github_raw")
    captured = utc_now_iso()
    rows = []
    for m in data.get("matches") or []:
        # The file gives a score as {"ht": [..], "ft": [..]}, or for some
        # matches as the bare full-time pair [home, away].
        score = m.get("score")
        ft = (score if isinstance(score, list) else (score or {}).get("ft")) or [
            None,
            None,
        ]
        rows.append(
            {
                "captured_at": captured,
                "season": data.get("name"),
                "round": m.get("round"),
                "date": m.get("date"),
                "time": m.get("time"),
                "team1": m.get("team1"),
                "team2": m.get("team2"),
                "goals1": ft[0],
                "goals2": ft[1],
            }
        )
    return _store(store, pool, "openfootball", "epl", rows)


def venue_schedules(store: ObjectStore, pool: Any) -> dict[str, Any]:
    with pool.connection() as conn:
        found = conn.execute(
            "select domain, market_id, question, event_title, end_date "
            "from tracked_markets where not closed"
        ).fetchall()
    captured = utc_now_iso()
    rows = [
        {
            "captured_at": captured,
            "domain": d,
            "market_id": m,
            "question": q,
            "event_title": e,
            "end_date": end.isoformat() if end else None,
        }
        for d, m, q, e, end in found
    ]
    return _store(store, pool, "venue_schedules", None, rows)


def gdelt(store: ObjectStore, pool: Any) -> dict[str, Any]:
    captured = utc_now_iso()
    rows = []
    for domain, adapter in DOMAINS.items():
        query = headline_query(adapter)
        if not query:
            continue
        payload = _get(
            GDELT,
            "gdelt",
            {
                "query": query,
                "mode": "artlist",
                "maxrecords": 50,
                "format": "json",
                "timespan": "24h",
            },
        )
        for a in (payload or {}).get("articles") or []:
            rows.append(
                {
                    "captured_at": captured,
                    "domain": domain,
                    "title": a.get("title"),
                    "url": a.get("url"),
                    "seen": a.get("seendate"),
                    "source": a.get("domain"),
                    "language": a.get("language"),
                }
            )
    return _store(store, pool, "gdelt", None, rows)


SOURCES: dict[str, Callable[[ObjectStore, Any], dict[str, Any]]] = {
    "open_meteo": open_meteo,
    "openfootball": openfootball,
    "venue_schedules": venue_schedules,
    "gdelt": gdelt,
}


def collect_evidence(ctx: JobContext) -> dict[str, Any]:
    """The `evidence` job: run each collector, each failing on its own."""
    names = ctx.job.payload.get("sources") or list(SOURCES)
    results: dict[str, Any] = {}
    for i, name in enumerate(names):
        ctx.progress(i / max(len(names), 1), name)
        try:
            results[name] = SOURCES[name](ctx.services.store, ctx.pool)
        except Exception as exc:  # noqa: BLE001 - one source's failure is reported
            logger.exception("evidence source %s failed", name)
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return results
