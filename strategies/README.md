# Strategies of your own

This folder holds strategies run by the harness on your own copy
(`docs/tutorials/your_own_strategy.md`). A strategy has up to two files:

- **`strategy.json`**: which markets, when to bet and how much. The demo
  downloads one; `example/strategy.json` is another. It is the platform's
  strategy spec (`vp/strategy/spec.py`, `docs/strategies.md`).
- **`forecast.py`** (optional): where the chances come from, as Python.
  Without it, the spec's own `belief` is used (one of the built-in
  forecasters, such as `elo`, or `market` for a rule that always backs the
  favourite or the underdog).

Run one:

```bash
uv run vp build-dataset --domain epl --histories 600   # once: past markets and prices
uv run vp strategy backtest strategies/example/strategy.json \
    --script strategies/example/forecast.py
```

Or, with nothing installed: on GitHub, *Actions*, *strategy*, *Run
workflow*, with the paths of your two files. The report is the run's
summary.

## For the AI writing the script

Point your AI (ChatGPT, Claude, Gemini, Copilot, a coding agent) at this
file and describe your idea. What it must write:

```python
def forecast(market, evidence) -> float | tuple[float, str] | None:
    """The chance, between 0 and 1, that the market's FIRST outcome happens
    (usually "Yes"), optionally with a one-line reason; None skips it."""
```

**`market`** (`vp/markets/schema.py`, `BinaryMarket`): `question` (text),
`domain` (`epl`, `cs2`, `weather`, ...), `parsed` (a dict of strings: always
`kind`, such as `match`, `daily_temperature`, `tournament_winner`, `total`;
then the kind's fields, listed per domain in `vp/domains/*.py` and
`vp/domains/packs/*.md`: for a match `team_a`, `team_b` and, in football,
`side`, the team the question is about), `event_id`, `event_title`,
`end_date`, `outcomes` (two, the first being the event forecast). Do not
use `resolved_outcome`, `winning_outcome`, `closed_time` or the prices on
the record: in a backtest they are what happened later.

**`evidence`** (`vp/forecast/evidence.py`, `Evidence`): everything known at
the time of the forecast, `evidence.cutoff`, and nothing after it.

| Call | Gives |
| :--- | :--- |
| `evidence.price_at(market)` | the market's price (its implied chance) at the cutoff, or None |
| `evidence.results(domain)` | settled matches: `settled`, `team_a`, `team_b`, `winner` (a name or `"draw"`); names are lower case without "FC" (`vp.forecast.evidence.canonical(name)` matches them) |
| `evidence.scores(domain)` | final scores of football matches |
| `evidence.table(domain)` | the league table of the season so far |
| `evidence.settled(domain)` | every market of the domain settled before the cutoff, with its label |
| `evidence.settled_prices(domain, hours)` | (settled, price that many hours before, label) for those markets |
| `evidence.event_prices(market)` | the other markets of the same event, with their prices |
| `evidence.daily_highs(city)` | realised daily temperatures at a city |
| `evidence.nwp(market)`, `evidence.ensemble(market)` | weather forecasts as issued (when the archive has them) |

**Rules that keep the result honest:**

1. Read the world only through `evidence`. No files, no web requests, no
   dates other than `evidence.cutoff`. (A script that calls an AI model is
   the one exception; see `example_ai/`, and note that a model may
   remember how past matches ended, so its backtest flatters it.)
2. Return None for markets the idea does not cover; do not guess 0.5.
3. Keep it deterministic: the same market and evidence give the same
   answer.
4. Return a chance for the first outcome, not for whichever side you like:
   the spec's rule decides which side to buy.

Then set the spec: `selector` (which markets), `rule.min_edge` (how much
better than the price after fees the chance must be, at least 0.03),
`sizing` (at most 5% of the balance on one market) and
`schedule.hours_before_close` (when the forecast is made). The backtest
prints the script's Brier score next to the market's: a script that does
not beat the market's own score has found no edge, whatever its profit.
