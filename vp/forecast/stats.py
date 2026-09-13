"""Statistical forecasters: Elo ratings for matches.

Elo is fitted on the settled results the evidence object serves, all of them
before the cutoff, replayed in settlement order from a common start rating.
For a match between $A$ (listed first, the home side in EPL fixtures) and
$B$, the expected score of $A$ is

$$E_A = \\frac{1}{1 + 10^{(R_B - R_A - H)/400}},$$

with $H$ a home advantage in rating points (0 for CS2, where the first team
is not a home side). After a result $S_A \\in \\{1, \\tfrac12, 0\\}$ both
ratings move by $K (S_A - E_A)$. The expected score mixes wins and draws, so
for a league with draws the win probability is recovered by removing the
draw mass: with empirical draw rate $d$ among the fitted results,
$P(A \\text{ wins}) = E_A - d/2$, clipped, and a draw market is forecast at
$d$. CS2 series cannot draw, so $P(A) = E_A$.

Parameters are conventional rather than fitted ($K = 32$, $H = 60$): the
point of the baseline is a sane rating from results alone, and tuning them
on the same resolved set the backtest scores would be a leak of its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from vp.forecast.base import Forecast, clip
from vp.forecast.evidence import Evidence, MatchResult, canonical
from vp.markets.schema import BinaryMarket


def fit_elo(
    results: list[MatchResult], *, k: float = 32.0, home: float = 0.0
) -> tuple[dict[str, float], float]:
    """Replay results in order; return ratings and the empirical draw rate."""
    ratings: dict[str, float] = {}
    draws = 0
    for r in results:
        ra = ratings.get(r.team_a, 1500.0)
        rb = ratings.get(r.team_b, 1500.0)
        expected = 1.0 / (1.0 + 10 ** ((rb - ra - home) / 400.0))
        score = 1.0 if r.winner == r.team_a else (0.5 if r.winner == "draw" else 0.0)
        draws += r.winner == "draw"
        ratings[r.team_a] = ra + k * (score - expected)
        ratings[r.team_b] = rb - k * (score - expected)
    draw_rate = draws / len(results) if results else 0.0
    return ratings, draw_rate


@dataclass(frozen=True)
class Elo:
    """Elo forecaster for ``match`` markets of one domain."""

    domain: str
    k: float = 32.0
    home: float = 0.0
    min_games: int = 3
    name: str = "elo"

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        p = market.parsed
        if market.domain != self.domain or p.get("kind") != "match":
            return None
        results = evidence.results(self.domain)
        ratings, draw_rate = fit_elo(results, k=self.k, home=self.home)
        a, b = canonical(p["team_a"]), canonical(p["team_b"])
        played = {a: 0, b: 0}
        for r in results:
            for t in (r.team_a, r.team_b):
                if t in played:
                    played[t] += 1
        if min(played.values()) < self.min_games:
            return None
        ra, rb = ratings.get(a, 1500.0), ratings.get(b, 1500.0)
        expected = 1.0 / (1.0 + 10 ** ((rb - ra - self.home) / 400.0))
        side = p.get("side")
        if side == "draw":
            p_hat = draw_rate
        else:
            p_a = expected - draw_rate / 2 if draw_rate else expected
            for_a = side is None or canonical(side) == a
            p_hat = p_a if for_a else 1.0 - p_a - draw_rate
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(p_hat),
            f"elo {a}={ra:.0f} ({played[a]} games), {b}={rb:.0f} ({played[b]} games), "
            f"E_A={expected:.3f}, draw rate {draw_rate:.3f}, side={side or a}",
        )
