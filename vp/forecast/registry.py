"""Append-only forecast registry, one JSON line per forecast.

Modelled on Vibe-Trading's hypothesis registry: a forecast, once made, is a
record of what was believed at the cutoff, and is never edited. The rationale
is stored in full and also hashed, so two runs that produced the same
reasoning can be matched without comparing text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

from vp.forecast.base import Forecast


class Registry:
    """JSONL file of forecasts."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, forecast: Forecast) -> None:
        """Write one forecast; creates the file and parents if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = asdict(forecast)
        row["rationale_sha256"] = hashlib.sha256(
            forecast.rationale.encode("utf-8")
        ).hexdigest()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    def read(self) -> Iterator[Forecast]:
        """Yield the forecasts in file order."""
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    row.pop("rationale_sha256", None)
                    yield Forecast(**row)
