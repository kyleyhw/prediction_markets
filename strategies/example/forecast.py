"""Recent form: a team's share of wins in its last matches, as its chance.

The belief of strategies/example/strategy.json. Run it with

    uv run vp strategy backtest strategies/example/strategy.json \
        --script strategies/example/forecast.py

Everything it reads comes through ``evidence``, which holds only what was
known when the forecast is made, so the backtest cannot see the future.
"""

from vp.forecast.evidence import canonical

#: How many of a team's latest matches count.
LAST = 10
#: How often the team named in a question wins, before any results: a
#: football match has three outcomes, so about a third.
PRIOR = 0.36
#: How many matches the prior is worth.
WEIGHT = 4


def forecast(market, evidence):
    fields = market.parsed
    if fields.get("kind") != "match":
        return None  # skip everything that is not a match
    team = canonical(fields.get("side") or fields["team_a"])
    games = [
        r for r in evidence.results(market.domain) if team in (r.team_a, r.team_b)
    ][-LAST:]
    wins = sum(r.winner == team for r in games)
    chance = (wins + PRIOR * WEIGHT) / (len(games) + WEIGHT)
    return chance, f"{team} won {wins} of its last {len(games)} matches"
