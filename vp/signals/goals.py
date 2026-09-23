"""Scoreline signals for football: Poisson and Dixon–Coles.

Final scores come from the venue's own resolved exact-score markets
(`Evidence.scores`), all settled before the cutoff. Each team has an attack
and a defence strength, shrunk toward the league average by three
pseudo-games so a team seen twice is not extreme; the home side's expected
goals are the league's home rate times its attack times the opponent's
defence, and the away side's likewise. The goals are independent Poisson
counts (Maher 1982), and Dixon and Coles (1997) add two things: a
correction $\\tau$ of the four lowest scores with a dependence $\\rho$ fitted
by likelihood on the past scores, and an exponential down-weighting of old
matches ($\\xi = 0.0065$ a day, a half-life of about 107 days).

One score grid prices every full-time market of the match: the result, the
total, a team's total, the spread, both teams to score and an exact score.
Halves are declined (the scores are full-time only), as is "any other
score" (its list of scores is the event's, not the grid's).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from vp.forecast.evidence import Evidence, MatchScore, canonical
from vp.markets.schema import BinaryMarket
from vp.signals.base import SignalMeta

KINDS = ("match", "total", "team_total", "spread", "both_teams_to_score", "exact_score")
GRID = 11  # goals 0..10 per side
SHRINK = 3.0
MIN_MATCHES = 3
XI = 0.0065


def _pois(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def _tau(i: int, j: int, la: float, lb: float, rho: float) -> float:
    if i == 0 and j == 0:
        return 1.0 - la * lb * rho
    if i == 0 and j == 1:
        return 1.0 + la * rho
    if i == 1 and j == 0:
        return 1.0 + lb * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


@dataclass(frozen=True)
class Model:
    home_rate: float
    away_rate: float
    attack: dict[str, float]
    defence: dict[str, float]
    games: dict[str, int]
    rho: float

    def rates(self, a: str, b: str) -> tuple[float, float]:
        return (
            self.home_rate * self.attack.get(a, 1.0) * self.defence.get(b, 1.0),
            self.away_rate * self.attack.get(b, 1.0) * self.defence.get(a, 1.0),
        )

    def grid(self, a: str, b: str) -> list[list[float]]:
        la, lb = self.rates(a, b)
        g = [
            [
                _pois(i, la) * _pois(j, lb) * _tau(i, j, la, lb, self.rho)
                for j in range(GRID)
            ]
            for i in range(GRID)
        ]
        total = sum(map(sum, g))
        return [[x / total for x in row] for row in g]


def fit(
    scores: list[MatchScore], *, xi: float, dixon_coles: bool, at: datetime
) -> Model | None:
    if not scores:
        return None
    weights = [math.exp(-xi * max((at - s.settled).days, 0)) for s in scores]
    total_w = sum(weights)
    home_rate = sum(w * s.goals_a for w, s in zip(weights, scores)) / total_w
    away_rate = sum(w * s.goals_b for w, s in zip(weights, scores)) / total_w
    mean = (home_rate + away_rate) / 2 or 1.0
    scored: dict[str, float] = {}
    conceded: dict[str, float] = {}
    played: dict[str, float] = {}
    games: dict[str, int] = {}
    for w, s in zip(weights, scores):
        for team, gf, ga in (
            (s.team_a, s.goals_a, s.goals_b),
            (s.team_b, s.goals_b, s.goals_a),
        ):
            scored[team] = scored.get(team, 0.0) + w * gf
            conceded[team] = conceded.get(team, 0.0) + w * ga
            played[team] = played.get(team, 0.0) + w
            games[team] = games.get(team, 0) + 1
    attack = {
        t: (scored[t] + SHRINK * mean) / (played[t] + SHRINK) / mean for t in played
    }
    defence = {
        t: (conceded[t] + SHRINK * mean) / (played[t] + SHRINK) / mean for t in played
    }
    model = Model(home_rate, away_rate, attack, defence, games, 0.0)
    if not dixon_coles:
        return model
    best, best_ll = 0.0, -math.inf
    for step in range(-20, 11):
        rho = step / 100
        ll = 0.0
        for w, s in zip(weights, scores):
            la, lb = model.rates(s.team_a, s.team_b)
            t = _tau(s.goals_a, s.goals_b, la, lb, rho)
            if t <= 0:
                ll = -math.inf
                break
            ll += w * math.log(t)
        if ll > best_ll:
            best, best_ll = rho, ll
    return Model(home_rate, away_rate, attack, defence, games, best)


def price(market: BinaryMarket, model: Model) -> float | None:
    """The market's probability from the score grid, or ``None``."""
    p = market.parsed
    kind = p.get("kind")
    if "team_a" not in p or "team_b" not in p:
        return None
    if p.get("period", "full") != "full" or p.get("stat", "goals") != "goals":
        return None
    a, b = canonical(p["team_a"]), canonical(p["team_b"])
    if min(model.games.get(a, 0), model.games.get(b, 0)) < MIN_MATCHES:
        return None
    g = model.grid(a, b)
    cells = [(i, j, g[i][j]) for i in range(GRID) for j in range(GRID)]
    team = canonical(p.get("team") or p.get("side") or "")
    if kind == "match":
        side = p.get("side")
        if side == "draw":
            return sum(x for i, j, x in cells if i == j)
        if side is None or team == a:
            return sum(x for i, j, x in cells if i > j)
        if team == b:
            return sum(x for i, j, x in cells if j > i)
        return None
    if kind == "total":
        line = float(p["line"])
        return sum(x for i, j, x in cells if i + j > line)
    if kind == "team_total":
        line = float(p["line"])
        if team == a:
            return sum(x for i, j, x in cells if i > line)
        if team == b:
            return sum(x for i, j, x in cells if j > line)
        return None
    if kind == "spread":
        line = float(p["line"])
        if team == a:
            return sum(x for i, j, x in cells if i - j + line > 0)
        if team == b:
            return sum(x for i, j, x in cells if j - i + line > 0)
        return None
    if kind == "both_teams_to_score":
        return sum(x for i, j, x in cells if i > 0 and j > 0)
    if kind == "exact_score":
        score = p.get("score", "")
        if "-" not in score:
            return None
        ga, gb = (int(x) for x in score.split("-"))
        return g[ga][gb] if ga < GRID and gb < GRID else 0.0
    return None


REFERENCES_POISSON = (
    "Maher, M. J. (1982). Modelling association football scores. Statistica "
    "Neerlandica 36(3), 109-118.",
)
REFERENCES_DC = REFERENCES_POISSON + (
    "Dixon, M. J. and Coles, S. G. (1997). Modelling association football "
    "scores and inefficiencies in the football betting market. Applied "
    "Statistics 46(2), 265-280.",
)


@dataclass
class GoalsSignal:
    dixon_coles: bool = False
    meta: SignalMeta = field(
        default_factory=lambda: SignalMeta(
            id="poisson",
            title="Poisson goals",
            domains=(),
            kinds=KINDS,
            accessors=("scores",),
            cutoff="final scores of matches settled before the cutoff",
            warmup="three scored matches for each team",
            references=REFERENCES_POISSON,
        )
    )
    _fits: dict[tuple[str, int], Model | None] = field(default_factory=dict, repr=False)

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None:
        domain = market.domain or ""
        scores = evidence.scores(domain)
        if not scores:
            return None
        # Refit when a score has been added or, with time decay, on a new day.
        day = evidence.cutoff.toordinal() if self.dixon_coles else 0
        key = (domain, len(scores) * 100_000 + day)
        if key not in self._fits:
            self._fits = {
                key: fit(
                    scores,
                    xi=XI if self.dixon_coles else 0.0,
                    dixon_coles=self.dixon_coles,
                    at=evidence.cutoff,
                )
            }
        model = self._fits[key]
        return None if model is None else price(market, model)


def dixon_coles() -> GoalsSignal:
    return GoalsSignal(
        dixon_coles=True,
        meta=SignalMeta(
            id="dixon_coles",
            title="Dixon-Coles goals",
            domains=(),
            kinds=KINDS,
            accessors=("scores",),
            cutoff="final scores of matches settled before the cutoff",
            warmup="three scored matches for each team",
            references=REFERENCES_DC,
        ),
    )
