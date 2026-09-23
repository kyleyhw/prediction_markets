"""Rating signals for match domains: Elo, Glicko-2, Bradley–Terry, map Elo.

Each is fitted on the settled results the evidence serves (all before the
cutoff) and answers match markets through :func:`vp.signals.base.to_market`:
the expected score of the first-listed team, less half the draw rate in a
sport with draws, gives the probability that it wins; a draw market gets
the draw rate. A domain whose first-listed team plays at home
(``Domain.home_first``) gives it a home advantage. A team with fewer than
three results before the cutoff is not rated, and the signal declines.

* **Elo** (Elo 1978; Hvattum and Arntzen 2010 for football): $K = 32$, home
  advantage 60 points, as the Phase 8 forecaster.
* **Glicko-2** (Glickman 2012): each result is a rating period of one game
  for both teams; rating deviation grows with inactivity only through the
  volatility, $\\tau = 0.5$; the win probability uses both teams' deviations.
* **Bradley–Terry** (Bradley and Terry 1952) with a home factor $\\theta$,
  $P(i \\text{ at home beats } j) = \\theta\\pi_i / (\\theta\\pi_i + \\pi_j)$,
  fitted by the minorise-maximise iteration of Hunter (2004) with a draw
  counted as half a win each and one pseudo-game against an average team
  per side, which keeps a new team's strength finite.
* **Map Elo**: Elo on CS2 map results only, answering map-winner markets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from vp.domains import DOMAINS
from vp.forecast.evidence import Evidence, MatchResult, canonical
from vp.forecast.stats import EloState, fit_elo
from vp.markets.schema import BinaryMarket
from vp.signals.base import SignalMeta, to_market

MIN_GAMES = 3
MATCH = ("match",)
RESULTS = ("results",)
CUTOFF = "results of matches settled before the cutoff"
WARMUP = "three settled results for each team"


def _teams(market: BinaryMarket) -> tuple[str, str] | None:
    p = market.parsed
    if "team_a" not in p or "team_b" not in p:
        return None
    return canonical(p["team_a"]), canonical(p["team_b"])


def _played(results: list[MatchResult], teams: tuple[str, str]) -> bool:
    counts = dict.fromkeys(teams, 0)
    for r in results:
        for t in (r.team_a, r.team_b):
            if t in counts:
                counts[t] += 1
    return min(counts.values()) >= MIN_GAMES


def _draw_rate(results: list[MatchResult]) -> float:
    return sum(r.winner == "draw" for r in results) / len(results) if results else 0.0


def _home(market: BinaryMarket) -> bool:
    domain = DOMAINS.get(market.domain or "")
    return bool(domain and domain.home_first)


def _score(r: MatchResult) -> float:
    return 1.0 if r.winner == r.team_a else (0.5 if r.winner == "draw" else 0.0)


@dataclass
class EloSignal:
    maps: bool = False
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="elo",
            title="Elo ratings",
            domains=(),
            kinds=MATCH,
            accessors=RESULTS,
            cutoff=CUTOFF,
            warmup=WARMUP,
            references=(
                "Elo, A. (1978). The Rating of Chessplayers, Past and Present.",
                "Hvattum, L. M. and Arntzen, H. (2010). Using ELO ratings for "
                "match result prediction in association football. International "
                "Journal of Forecasting 26(3), 460-470.",
            ),
        )
    )
    _states: dict[str, EloState] = field(default_factory=dict, repr=False)

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        teams = _teams(market)
        if teams is None or ("map" in market.parsed) != self.maps:
            return None
        domain = market.domain or ""
        results = evidence.results(domain, maps=self.maps)
        if not _played(results, teams):
            return None
        home = 60.0 if _home(market) else 0.0
        key = f"{domain}:{self.maps}"
        self._states[key] = fit_elo(results, home=home, state=self._states.get(key))
        ratings = self._states[key].ratings
        ra, rb = ratings.get(teams[0], 1500.0), ratings.get(teams[1], 1500.0)
        expected = 1.0 / (1.0 + 10 ** ((rb - ra - home) / 400.0))
        draws = _draw_rate(results)
        return to_market(expected - draws / 2, draws, market, teams[0])


def map_elo() -> EloSignal:
    return EloSignal(
        maps=True,
        meta=SignalMeta(
            id="map_elo",
            title="Elo ratings on single maps",
            domains=(),
            kinds=MATCH,
            accessors=RESULTS,
            cutoff="results of single maps settled before the cutoff",
            warmup="three settled maps for each team",
            references=(
                "Elo, A. (1978). The Rating of Chessplayers, Past and Present.",
            ),
            extra={"answers": "map-winner markets only"},
        ),
    )


# ------------------------------------------------------------------ Glicko-2

_SCALE = 173.7178
_TAU = 0.5
_EPS = 1e-6


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / math.pi**2)


def _glicko_update(
    mu: float, phi: float, sigma: float, mu_j: float, phi_j: float, s: float
) -> tuple[float, float, float]:
    """One rating period with one game (Glickman 2012, steps 3 to 8)."""
    g = _g(phi_j)
    e = 1.0 / (1.0 + math.exp(-g * (mu - mu_j)))
    v = 1.0 / (g * g * e * (1.0 - e))
    delta = v * g * (s - e)
    a = math.log(sigma * sigma)

    def f(x: float) -> float:
        ex = math.exp(x)
        return (ex * (delta**2 - phi**2 - v - ex)) / (2.0 * (phi**2 + v + ex) ** 2) - (
            x - a
        ) / _TAU**2

    lo = a
    if delta**2 > phi**2 + v:
        hi = math.log(delta**2 - phi**2 - v)
    else:
        k = 1
        while f(a - k * _TAU) < 0:
            k += 1
        hi = a - k * _TAU
    f_lo, f_hi = f(lo), f(hi)
    while abs(hi - lo) > _EPS:
        c = lo + (lo - hi) * f_lo / (f_hi - f_lo)
        f_c = f(c)
        if f_c * f_hi <= 0:
            lo, f_lo = hi, f_hi
        else:
            f_lo /= 2.0
        hi, f_hi = c, f_c
    sigma_new = math.exp(lo / 2.0)
    phi_star = math.sqrt(phi * phi + sigma_new * sigma_new)
    phi_new = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    mu_new = mu + phi_new * phi_new * g * (s - e)
    return mu_new, phi_new, sigma_new


@dataclass
class Glicko2Signal:
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="glicko2",
            title="Glicko-2 ratings",
            domains=(),
            kinds=MATCH,
            accessors=RESULTS,
            cutoff=CUTOFF,
            warmup=WARMUP,
            references=(
                "Glickman, M. E. (2012). Example of the Glicko-2 system. "
                "Boston University.",
            ),
        )
    )
    _fits: dict[str, tuple[int, dict[str, tuple[float, float, float]]]] = field(
        default_factory=dict, repr=False
    )

    def _fit(
        self, key: str, results: list[MatchResult], home: float
    ) -> dict[str, tuple[float, float, float]]:
        done, ratings = self._fits.get(key, (0, {}))
        if done > len(results):
            done, ratings = 0, {}
        ratings = dict(ratings)
        start = (0.0, 350.0 / _SCALE, 0.06)
        for r in results[done:]:
            a = ratings.get(r.team_a, start)
            b = ratings.get(r.team_b, start)
            s = _score(r)
            new_a = _glicko_update(a[0] + home, a[1], a[2], b[0], b[1], s)
            new_b = _glicko_update(b[0], b[1], b[2], a[0] + home, a[1], 1.0 - s)
            ratings[r.team_a] = (new_a[0] - home, new_a[1], new_a[2])
            ratings[r.team_b] = new_b
        self._fits[key] = (len(results), ratings)
        return ratings

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        teams = _teams(market)
        if teams is None or "map" in market.parsed:
            return None
        domain = market.domain or ""
        results = evidence.results(domain)
        if not _played(results, teams):
            return None
        home = 60.0 / _SCALE if _home(market) else 0.0
        ratings = self._fit(domain, results, home)
        a, b = ratings[teams[0]], ratings[teams[1]]
        spread = math.sqrt(a[1] ** 2 + b[1] ** 2)
        expected = 1.0 / (1.0 + math.exp(-_g(spread) * (a[0] + home - b[0])))
        draws = _draw_rate(results)
        return to_market(expected - draws / 2, draws, market, teams[0])


# -------------------------------------------------------------- Bradley–Terry


@dataclass
class BradleyTerrySignal:
    iterations: int = 60
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="bradley_terry",
            title="Bradley-Terry strengths",
            domains=(),
            kinds=MATCH,
            accessors=RESULTS,
            cutoff=CUTOFF,
            warmup=WARMUP,
            references=(
                "Bradley, R. A. and Terry, M. E. (1952). Rank analysis of "
                "incomplete block designs. Biometrika 39, 324-345.",
                "Hunter, D. R. (2004). MM algorithms for generalized Bradley-Terry "
                "models. Annals of Statistics 32(1), 384-406.",
            ),
        )
    )
    _fits: dict[str, tuple[int, dict[str, float], float]] = field(
        default_factory=dict, repr=False
    )

    def _fit(
        self, key: str, results: list[MatchResult], with_home: bool
    ) -> tuple[dict[str, float], float]:
        cached = self._fits.get(key)
        if cached is not None and cached[0] == len(results):
            return cached[1], cached[2]
        teams = sorted({t for r in results for t in (r.team_a, r.team_b)})
        index = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        # Each team plays one pseudo-game at home and one away against an
        # average team (strength 1), winning half of each.
        wins = [1.0] * n
        games = [(index[r.team_a], index[r.team_b], _score(r)) for r in results]
        for h, a, s in games:
            wins[h] += s
            wins[a] += 1.0 - s
        # Half of each pseudo-game is a home win: the team's at home, and the
        # average team's when it hosts.
        home_wins = sum(s for _, _, s in games) + n * 1.0
        pi = [1.0] * n
        theta = 1.0
        for _ in range(self.iterations):
            denom = [0.0] * n
            home_denom = 0.0
            for h, a, _ in games:
                d = theta * pi[h] + pi[a]
                denom[h] += theta / d
                denom[a] += 1.0 / d
                home_denom += pi[h] / d
            for i in range(n):
                denom[i] += theta / (theta * pi[i] + 1.0) + 1.0 / (pi[i] + theta)
                home_denom += pi[i] / (theta * pi[i] + 1.0) + 1.0 / (theta + pi[i])
            pi = [wins[i] / denom[i] for i in range(n)]
            scale = math.exp(sum(math.log(p) for p in pi) / n) if n else 1.0
            pi = [p / scale for p in pi]
            if with_home:
                theta = home_wins / home_denom
        strengths = {t: pi[index[t]] for t in teams}
        self._fits[key] = (len(results), strengths, theta)
        return strengths, theta

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        teams = _teams(market)
        if teams is None or "map" in market.parsed:
            return None
        domain = market.domain or ""
        results = evidence.results(domain)
        if not _played(results, teams):
            return None
        home = _home(market)
        strengths, theta = self._fit(domain, results, home)
        a, b = strengths[teams[0]], strengths[teams[1]]
        t = theta if home else 1.0
        expected = t * a / (t * a + b)
        draws = _draw_rate(results)
        return to_market(expected - draws / 2, draws, market, teams[0])
