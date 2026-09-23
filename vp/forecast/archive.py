"""The evidence archive as the engine reads it (plan, task 72;
docs/evidence.md).

Captures live under ``<root>/evidence/<source>/<YYYY-MM-DD>/``, one Parquet
file and one JSON manifest per capture, the layout the platform's
collectors write under ``shared/evidence/``. Every row has ``captured_at``;
a row from a point-in-time provider also has ``available_at``, the latest
moment the value can have existed. A reader sees a row only if that moment
(``available_at``, else ``captured_at``) is before its cutoff, and reads a
capture only if the file's hash matches its manifest.
"""

from __future__ import annotations

import hashlib
import json
import logging
from bisect import bisect_left
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# What each source is and under which terms; written into every manifest.
LICENCES = {
    "open_meteo": "Open-Meteo, CC BY 4.0; free API non-commercial (F9)",
    "open_meteo_runs": "Open-Meteo Previous Runs API, CC BY 4.0; point in time",
    "open_meteo_ensemble": "Open-Meteo Ensemble API, CC BY 4.0",
    "stations": "Aviation Weather Center (NOAA), public domain",
    "openfootball": "openfootball football.json, CC0 1.0",
    "venue_schedules": "the venue's public market data",
    "gdelt": "GDELT Project, open with attribution; titles and links only",
}
# Sources whose rows may carry an `available_at` before their capture.
POINT_IN_TIME = {"open_meteo_runs", "openfootball"}


def _stamp(when: datetime) -> str:
    return when.strftime("%Y%m%dT%H%M%S%fZ")


def write_capture(
    root: Path,
    source: str,
    rows: list[dict[str, Any]],
    *,
    provenance: dict[str, Any],
    now: datetime | None = None,
) -> Path | None:
    """Write one capture and its manifest; returns the Parquet path."""
    if not rows:
        return None
    now = now or datetime.now(tz=UTC)
    if source not in POINT_IN_TIME and any("available_at" in r for r in rows):
        raise ValueError(f"{source} is not a point-in-time source")
    if source in POINT_IN_TIME:  # a value not yet final waits for a later run
        rows = [r for r in rows if parse_when(r.get("available_at") or now) <= now]
        if not rows:
            return None
    folder = root / "evidence" / source / f"{now:%Y-%m-%d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_stamp(now)}.parquet"
    stamped = [{"captured_at": now.isoformat(), **r} for r in rows]
    pq.write_table(pa.Table.from_pylist(stamped), path)
    path.with_suffix(".json").write_text(
        json.dumps(manifest(source, path, len(rows), now, provenance), indent=1)
    )
    return path


def manifest(
    source: str, path: Path, rows: int, now: datetime, provenance: dict[str, Any]
) -> dict[str, Any]:
    return {
        "source": source,
        "captured_at": now.isoformat(),
        "rows": rows,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "licence": LICENCES.get(source, ""),
        "provenance": provenance,
        "visibility": "available_at" if source in POINT_IN_TIME else "captured_at",
    }


def parse_when(text: Any) -> datetime:
    if isinstance(text, datetime):
        return text
    when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


class Archive:
    """Every capture of a source, loaded once and served up to a cutoff."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._rows: dict[str, tuple[list[datetime], list[dict[str, Any]]]] = {}

    def _load(self, source: str) -> tuple[list[datetime], list[dict[str, Any]]]:
        if source in self._rows:
            return self._rows[source]
        rows: list[dict[str, Any]] = []
        for path in sorted((self.root / "evidence" / source).glob("*/*.parquet")):
            meta = path.with_suffix(".json")
            if meta.exists():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if json.loads(meta.read_text()).get("sha256") != digest:
                    logger.warning("capture %s does not match its manifest", path)
                    continue
            point = source in POINT_IN_TIME
            for r in pq.read_table(path).to_pylist():
                seen = r.get("available_at") if point else None
                r["_visible"] = parse_when(seen or r["captured_at"])
                rows.append(r)
        rows.sort(key=lambda r: r["_visible"])
        self._rows[source] = ([r["_visible"] for r in rows], rows)
        return self._rows[source]

    def rows(self, source: str, cutoff: datetime) -> list[dict[str, Any]]:
        """The source's rows visible before ``cutoff``, oldest first."""
        times, rows = self._load(source)
        return rows[: bisect_left(times, cutoff)]
