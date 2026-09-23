"""The signal registry: ids to signals, loaded on first use.

Each call to :func:`load` returns fresh instances (a signal caches its fits,
and a backtest or bench should start clean). :func:`manifest` is what
`vp signals list` prints: each signal's metadata and the hash of its
module's source, so a bench result names exactly the code it measured.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from vp.signals.base import Signal


def _factories() -> dict[str, Callable[[], Signal]]:
    from vp.signals import goals, market, ratings, weather

    return {
        "elo": ratings.EloSignal,
        "glicko2": ratings.Glicko2Signal,
        "bradley_terry": ratings.BradleyTerrySignal,
        "map_elo": ratings.map_elo,
        "poisson": goals.GoalsSignal,
        "dixon_coles": goals.dixon_coles,
        "climatology": weather.ClimatologySignal,
        "persistence": weather.PersistenceSignal,
        "bucket_normalised": weather.BucketNormalisedSignal,
        "platt_market": market.CalibratedMarket,
        "isotonic_market": market.isotonic_market,
    }


def ids() -> tuple[str, ...]:
    return tuple(_factories())


def load(signal_id: str) -> Signal:
    try:
        return _factories()[signal_id]()
    except KeyError:
        raise ValueError(f"no signal {signal_id!r}; choose from {ids()}") from None


def load_all() -> list[Signal]:
    return [factory() for factory in _factories().values()]


def module_hash(signal: Signal) -> str:
    source = inspect.getsource(inspect.getmodule(type(signal)) or type(signal))
    return hashlib.sha256(source.encode()).hexdigest()


def manifest() -> list[dict[str, Any]]:
    return [{**asdict(s.meta), "module_sha256": module_hash(s)} for s in load_all()]
