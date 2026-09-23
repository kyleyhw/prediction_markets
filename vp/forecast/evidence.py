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
* ``scores``: final scores of football matches settled before $t$, read the
  same way from resolved exact-score markets (Phase 16).
* ``event_prices``: the other markets of the market's event with their
  prices at $t$ and every label removed (Phase 16).
* ``settled_prices``: for markets settled before $t$, the price each had a
  fixed time before its own settlement, and its label: what a calibration
  of the market price is fitted on (Phase 16).
* ``nwp``, ``ensemble``, ``headlines``: rows of the evidence archive
  visible before $t$ (``vp.forecast.archive``, Phase 17): the point-in-time
  weather forecasts and the ensemble members at the station a market names,
  and the headlines captured for a domain.

Using the dataset as its own evidence source is a deliberate choice for the
backtest: it is complete for every market in the set, it is free, and it
cannot leak because the settlement time is part of every record. Its cost is
coverage (a team's results exist only where the venue listed the match) and
bucket resolution (a temperature is known to the bucket, not the degree).
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from vp.domains import DOMAINS
from vp.domains.weather import station
from vp.forecast.archive import Archive
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
class MatchScore:
    """A settled football match's final score, home side first."""

    settled: datetime
    team_a: str
    team_b: str
    goals_a: int
    goals_b: int


@dataclass(frozen=True)
class NwpDay:
    """A day's forecast extremes (°C) at a station, issued ``lead_days`` ahead."""

    day: date
    lead_days: int
    tmax: float
    tmin: float


@dataclass
class Standing:
    """A team's line in a league table derived from results before the cutoff."""

    team: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def points(self) -> int:
        return 3 * self.won + self.drawn


@dataclass(frozen=True)
class Headline:
    title: str
    url: str
    source: str
    captured_at: datetime


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
        cache: Shared index store, so views at many cutoffs (a backtest)
            load and sort the resolved sets once; see :meth:`at`.
    """

    def __init__(
        self,
        cutoff: datetime,
        root: Path,
        *,
        markets: dict[str, list[BinaryMarket]] | None = None,
        cache: dict[str, Any] | None = None,
        live: list[BinaryMarket] | None = None,
    ) -> None:
        if cutoff.tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        self.cutoff = cutoff.astimezone(timezone.utc)
        self.root = root
        cache = cache if cache is not None else {}
        self._markets: dict[str, list[BinaryMarket]] = cache.setdefault("markets", {})
        self._markets.update(markets or {})
        self._results: dict[str, list[MatchResult]] = cache.setdefault("results", {})
        self._highs: dict[str, dict[str, list[Observation]]] = cache.setdefault(
            "highs", {}
        )
        self._cache = cache
        self._archive: Archive = cache.setdefault("archive", Archive(root))
        # Markets trading now (the paper loop's capture): their prices are
        # the present, so they answer `event_prices` for open events.
        self._live = live or []

    def at(self, cutoff: datetime) -> Evidence:
        """A new view at another cutoff sharing this object's loaded indexes."""
        return Evidence(cutoff, self.root, cache=self._cache, live=self._live)

    def _resolved(self, domain: str) -> list[BinaryMarket]:
        if domain not in self._markets:
            path = self.root / "markets" / domain / "resolved.parquet"
            self._markets[domain] = read_markets(path) if path.exists() else []
        return self._markets[domain]

    def _history(self, domain: str, market_id: str) -> list[tuple[datetime, float]]:
        """A market's stored price series, read once per process view."""
        cache = self._cache.setdefault("histories", {})
        key = f"{domain}/{market_id}"
        if key not in cache:
            path = self.root / "histories" / domain / f"{market_id}.parquet"
            points = []
            if path.exists():
                for row in read_history(path):
                    stamp = parse_time(row["timestamp"])
                    if stamp is not None:
                        points.append((stamp, row["implied_probability"]))
            cache[key] = points
        return cache[key]

    def _price_before(
        self, domain: str, market_id: str, when: datetime
    ) -> float | None:
        price = None
        for stamp, p in self._history(domain, market_id):
            if stamp > when:
                break
            price = p
        return price

    def price_at(self, market: BinaryMarket) -> float | None:
        """Last stored price of the first outcome at or before the cutoff."""
        if market.domain is None or market.market_id is None:
            return None
        return self._price_before(market.domain, market.market_id, self.cutoff)

    def event_prices(
        self, market: BinaryMarket
    ) -> list[tuple[BinaryMarket, float | None]]:
        """The market's event, itself included, each with its price at the
        cutoff; the labels are removed, since a sibling's outcome is later."""
        if market.event_id is None or market.domain is None:
            return []
        live = [m for m in self._live if m.event_id == market.event_id]
        if live:
            return [(_unlabelled(m), m.p_yes) for m in live]
        siblings = [
            m for m in self._resolved(market.domain) if m.event_id == market.event_id
        ]
        return [(_unlabelled(m), self.price_at(m)) for m in siblings]

    def settled(self, domain: str) -> list[BinaryMarket]:
        """The domain's markets settled (with a label) before the cutoff."""
        return [
            m
            for m in self._resolved(domain)
            if m.resolved_outcome is not None
            and (when := settled_at(m)) is not None
            and when < self.cutoff
        ]

    def settled_prices(
        self, domain: str, hours: float
    ) -> list[tuple[datetime, float, int]]:
        """(settled, price ``hours`` before settling, label) for the domain's
        markets settled before the cutoff that had a price then."""
        cache = self._cache.setdefault("settled_prices", {})
        key = (domain, hours)
        if key not in cache:
            rows = []
            for m in self._resolved(domain):
                when = settled_at(m)
                if when is None or m.resolved_outcome is None or m.market_id is None:
                    continue
                q = self._price_before(
                    domain, m.market_id, when - timedelta(hours=hours)
                )
                if q is not None:
                    rows.append((when, q, m.resolved_outcome))
            rows.sort(key=lambda r: r[0])
            cache[key] = rows
        rows = cache[key]
        return rows[: bisect_left([r[0] for r in rows], self.cutoff)]

    def scores(self, domain: str) -> list[MatchScore]:
        """Final scores of matches settled before the cutoff, from the
        venue's resolved exact-score markets, in order."""
        cache = self._cache.setdefault("scores", {})
        if domain not in cache:
            from vp.domains import DOMAINS

            reader = DOMAINS.get(domain)
            seen: dict[tuple[str, str, str], MatchScore] = {}
            for m in self._resolved(domain):
                if m.resolved_outcome != 1:
                    continue
                p = m.parsed
                if p.get("kind") != "exact_score" and reader is not None:
                    p = reader.read(m.question, m.event_title) or {}
                if p.get("kind") != "exact_score" or p.get("period") != "full":
                    continue
                score = p.get("score", "")
                when = settled_at(m)
                if "-" not in score or when is None:
                    continue
                goals_a, goals_b = (int(x) for x in score.split("-"))
                a, b = canonical(p["team_a"]), canonical(p["team_b"])
                seen[(a, b, when.date().isoformat())] = MatchScore(
                    when, a, b, goals_a, goals_b
                )
            cache[domain] = sorted(seen.values(), key=lambda s: s.settled)
        rows = cache[domain]
        return rows[: bisect_left([s.settled for s in rows], self.cutoff)]

    def results(self, domain: str, *, maps: bool = False) -> list[MatchResult]:
        """Settled match results in ``domain`` known before the cutoff, in
        order: whole matches, or with ``maps`` single maps only."""
        key = f"{domain}:maps" if maps else domain
        if key not in self._results:
            out: list[MatchResult] = []
            for m in self._resolved(domain):
                if m.parsed.get("kind") != "match" or ("map" in m.parsed) != maps:
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
            self._results[key] = out
        rows = self._results[key]
        return rows[: bisect_left([r.settled for r in rows], self.cutoff)]

    def daily_highs(self, city: str, statistic: str = "highest") -> list[Observation]:
        """Realised daily temperatures at ``city`` for dates before the cutoff."""
        key = f"{statistic}:{city.lower()}"
        cities = self._highs.setdefault("observed", {})
        if key not in cities:
            seen: dict[date, Observation] = {}
            observed = [n for n, d in DOMAINS.items() if d.observes]
            for m in (m for n in observed for m in self._resolved(n)):
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

    def nwp(self, market: BinaryMarket) -> list[NwpDay]:
        """Point-in-time forecasts at the market's station, by day and lead."""
        code = station(market.resolution_source)
        if code is None:
            return []
        return [
            NwpDay(date.fromisoformat(r["day"]), r["lead_days"], r["tmax"], r["tmin"])
            for r in self._archive.rows("open_meteo_runs", self.cutoff)
            if r["station"] == code
        ]

    def ensemble(self, market: BinaryMarket) -> list[tuple[float, float | None]]:
        """The members (max, min °C) for the market's day from the newest
        capture before the cutoff; empty if none covers it."""
        code, day = station(market.resolution_source), market_date(market)
        if code is None or day is None:
            return []
        rows = [
            r
            for r in self._archive.rows("open_meteo_ensemble", self.cutoff)
            if r["station"] == code and r["day"] == day.isoformat()
        ]
        if not rows:
            return []
        newest = max(r["captured_at"] for r in rows)
        return [(r["tmax"], r["tmin"]) for r in rows if r["captured_at"] == newest]

    def table(self, domain: str) -> list[Standing]:
        """The league table of the season the cutoff falls in, from the
        results known before it; best first (points, goal difference,
        goals scored)."""
        day = self.cutoff.date()
        start = date(day.year if day.month >= 8 else day.year - 1, 8, 1)
        played: dict[tuple[str, str, str], dict[str, Any]] = {}
        for r in self._archive.rows("openfootball", self.cutoff):
            if (
                r.get("domain") == domain
                and r.get("goals1") is not None
                and start.isoformat() <= (r.get("date") or "") < day.isoformat()
            ):
                played[(r["date"], r["team1"], r["team2"])] = r
        teams: dict[str, Standing] = {}
        for r in played.values():
            home = teams.setdefault(
                canonical(r["team1"]), Standing(canonical(r["team1"]))
            )
            away = teams.setdefault(
                canonical(r["team2"]), Standing(canonical(r["team2"]))
            )
            for side, other, gf, ga in ((home, away, r["goals1"], r["goals2"]),):
                side.played += 1
                other.played += 1
                side.goals_for += gf
                side.goals_against += ga
                other.goals_for += ga
                other.goals_against += gf
                if gf > ga:
                    side.won += 1
                    other.lost += 1
                elif gf < ga:
                    side.lost += 1
                    other.won += 1
                else:
                    side.drawn += 1
                    other.drawn += 1
        return sorted(
            teams.values(),
            key=lambda s: (-s.points, s.goals_against - s.goals_for, -s.goals_for),
        )

    def headlines(self, domain: str, hours: float = 24.0) -> list[Headline]:
        """Headlines captured for ``domain`` in the ``hours`` before the cutoff,
        newest first, each title once."""
        since = self.cutoff - timedelta(hours=hours)
        seen: set[str] = set()
        out = []
        for r in reversed(self._archive.rows("gdelt", self.cutoff)):
            if r["_visible"] < since:
                break
            if r.get("domain") == domain and r.get("title") not in seen:
                seen.add(r["title"])
                out.append(
                    Headline(r["title"], r["url"], r.get("source") or "", r["_visible"])
                )
        return out


def _unlabelled(m: BinaryMarket) -> BinaryMarket:
    return replace(
        m, resolved_outcome=None, winning_outcome=None, resolution_state="unknown"
    )


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
