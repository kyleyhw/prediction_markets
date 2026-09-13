"""Cutoff-bounded evidence: everything a forecaster is allowed to read.

The evidence object is built with the cutoff $t$ and a data root, and every
accessor filters what it returns to information known before $t$:

* ``price_at``: the last stored price of the market's first outcome at or
  before $t$, from the histories the dataset builder wrote.
* ``results``: settled match results in a domain whose settlement time is
  before $t$, read from the resolved market set itself, with team names
  canonicalised (see :func:`canonical`). Polymarket's own
  resolutions are the results source: a resolved match market names the
  winner and carries the venue's closing time, so no external results feed
  is needed and the cutoff is enforced on the same clock as the labels.
* ``daily_highs``: realised daily maximum temperatures at a city for dates
  before $t$, read from resolved daily-temperature markets: exactly one
  bucket of each event resolves Yes, and its bounds are the observation.

Using the dataset as its own evidence source is a deliberate choice for the
backtest: it is complete for every market in the set, it is free, and it
cannot leak because the settlement time is part of every record. Its cost is
coverage (a team's results exist only where the venue listed the match) and
bucket resolution (a temperature is known to the bucket, not the degree).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from vp.markets.schema import BinaryMarket
from vp.markets.store import read_history, read_markets

_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}


def parse_time(text: str | None) -> datetime | None:
    """Parse the venue's timestamp forms (``...Z`` or ``... +00``) as aware UTC."""
    if not text:
        return None
    text = text.strip().replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def settled_at(market: BinaryMarket) -> datetime | None:
    """When the market's result became known: its closing time, else end date."""
    return parse_time(market.closed_time) or parse_time(market.end_date)


def market_date(market: BinaryMarket) -> date | None:
    """Calendar date of a daily-temperature market, from its parsed ``date``.

    The question carries month and day only; the year is the end date's.
    """
    text = market.parsed.get("date", "")
    end = parse_time(market.end_date)
    parts = text.replace(",", "").split()
    if end is None or len(parts) != 2 or parts[0].lower() not in _MONTHS:
        return None
    try:
        return date(end.year, _MONTHS[parts[0].lower()], int(parts[1]))
    except ValueError:
        return None


@dataclass(frozen=True)
class MatchResult:
    """A settled match: who played, who won, when it settled."""

    settled: datetime
    team_a: str
    team_b: str
    winner: str  # team name, or "draw"
    domain: str


@dataclass(frozen=True)
class Observation:
    """A realised daily maximum temperature known to its bucket."""

    day: date
    low: float | None
    high: float | None
    unit: str

    @property
    def value(self) -> float:
        """Bucket midpoint, or the bound of an open-ended bucket."""
        if self.low is not None and self.high is not None:
            return (self.low + self.high) / 2
        return self.low if self.low is not None else float(self.high or 0.0)


def _float(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


_SUFFIXES = (" fc", " afc", " cf", " sc")


def canonical(team: str) -> str:
    """Normalise a team name across the venue's eras.

    The 2024 fixtures say ``Arsenal`` and the 2026 ones ``Arsenal FC``; the
    club suffix is dropped and case folded so both rate the same team.
    """
    name = " ".join(team.split()).lower()
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


class Evidence:
    """Cutoff-bounded reads over the data root.

    Args:
        cutoff: The information cutoff; nothing at or after it is served.
        root: Data root written by ``vp build-dataset``.
        markets: Resolved markets to derive results and observations from;
            loaded from the root per domain on first use when omitted.
    """

    def __init__(
        self,
        cutoff: datetime,
        root: Path,
        *,
        markets: dict[str, list[BinaryMarket]] | None = None,
    ) -> None:
        if cutoff.tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        self.cutoff = cutoff.astimezone(timezone.utc)
        self.root = root
        self._markets = dict(markets or {})
        self._results: dict[str, list[MatchResult]] = {}
        self._highs: dict[str, dict[str, list[Observation]]] = {}

    def _resolved(self, domain: str) -> list[BinaryMarket]:
        if domain not in self._markets:
            path = self.root / "markets" / domain / "resolved.parquet"
            self._markets[domain] = read_markets(path) if path.exists() else []
        return self._markets[domain]

    def price_at(self, market: BinaryMarket) -> float | None:
        """Last stored price of the first outcome at or before the cutoff."""
        if market.domain is None or market.market_id is None:
            return None
        path = self.root / "histories" / market.domain / f"{market.market_id}.parquet"
        if not path.exists():
            return None
        price = None
        for row in read_history(path):
            stamp = parse_time(row["timestamp"])
            if stamp is None or stamp > self.cutoff:
                break
            price = row["implied_probability"]
        return price

    def results(self, domain: str) -> list[MatchResult]:
        """Settled match results in ``domain`` known before the cutoff, in order."""
        if domain not in self._results:
            out: list[MatchResult] = []
            for m in self._resolved(domain):
                if m.parsed.get("kind") != "match" or "map" in m.parsed:
                    continue
                when = settled_at(m)
                if when is None or m.resolved_outcome is None:
                    continue
                winner = _winner(m)
                if winner is None:
                    continue
                out.append(
                    MatchResult(
                        when,
                        canonical(m.parsed["team_a"]),
                        canonical(m.parsed["team_b"]),
                        canonical(winner) if winner != "draw" else "draw",
                        domain,
                    )
                )
            out.sort(key=lambda r: r.settled)
            self._results[domain] = out
        return [r for r in self._results[domain] if r.settled < self.cutoff]

    def daily_highs(self, city: str, statistic: str = "highest") -> list[Observation]:
        """Realised daily temperatures at ``city`` for dates before the cutoff."""
        key = f"{statistic}:{city.lower()}"
        cities = self._highs.setdefault("weather", {})
        if key not in cities:
            seen: dict[date, Observation] = {}
            for m in self._resolved("weather"):
                p = m.parsed
                if (
                    p.get("kind") != "daily_temperature"
                    or m.resolved_outcome != 1
                    or p.get("city", "").lower() != city.lower()
                    or p.get("statistic") != statistic
                ):
                    continue
                day = market_date(m)
                if day is None:
                    continue
                seen[day] = Observation(
                    day, _float(p["low"]), _float(p["high"]), p["unit"]
                )
            cities[key] = sorted(seen.values(), key=lambda o: o.day)
        return [o for o in cities[key] if o.day < self.cutoff.date()]


def _winner(m: BinaryMarket) -> str | None:
    """Name the winner of a resolved match market from its label and question.

    A Yes/No side market (``Will A win?`` with ``side``) resolving Yes names
    the side; resolving No says only that the side did not win, which is not
    a result on its own, so it is skipped: the sibling market that resolved
    Yes carries it. A two-team market (outcomes are the teams) names the
    winner directly.
    """
    side = m.parsed.get("side")
    if side is not None:
        return side if m.resolved_outcome == 1 else None
    names = (m.outcomes[0].name, m.outcomes[1].name)
    if names in (("Yes", "No"), ("No", "Yes")):
        return None
    return m.parsed["team_a"] if m.resolved_outcome == 1 else m.parsed["team_b"]
