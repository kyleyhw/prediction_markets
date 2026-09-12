"""Domain adapters: which Polymarket markets belong to each domain, and how to
read their questions into structured fields."""

from __future__ import annotations

from vp.domains.base import Domain
from vp.domains.cs2 import CS2
from vp.domains.epl import EPL
from vp.domains.weather import WEATHER

DOMAINS: dict[str, Domain] = {d.name: d for d in (CS2, WEATHER, EPL)}

__all__ = ["CS2", "DOMAINS", "EPL", "WEATHER", "Domain"]
