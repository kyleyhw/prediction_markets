# Signals, Blends, Committees and the Benchmark

Phase 16's design: the systematic answer to "does anything beat the
market". A **signal** is a small, tested, cutoff-safe function from a
market and its evidence to a probability; the **bench** scores every signal
against the market on the same markets with an interval; a **blend**
combines signals with the market price, fitted only on the past; a
**committee** is several model roles and a rule to combine them; the
**benchmark** commits forecasts before the answers exist. A strategy's
belief (`docs/strategies.md`) can name any of them. Written on 2026-09-23
before the code, under the owner's goal to build the next three phases (14
to 16); the choices below were made as the plan proposes them.

## The Contract

```python
class Signal(Protocol):
    meta: SignalMeta

    def compute(self, market: BinaryMarket, evidence: Evidence) -> float | None: ...
```

`compute` returns the probability of the market's first outcome, or `None`
to decline (not its kind, not enough history). Version 1 signals are all
probabilities, so each can be benched and used as a belief as it is;
features that are not probabilities (rest days, depth imbalance) enter
through blends later. `SignalMeta` carries:

| Field | Meaning |
| :--- | :--- |
| `id` | stable name, used as `signal:<id>` in a spec's belief |
| `domains`, `kinds` | where it applies; checked before `compute` is called |
| `accessors` | the evidence it reads (`results`, `scores`, `daily_highs`, `price_at`, `event_prices`, `settled_prices`) |
| `cutoff` | in words, what "before the cutoff" means for it |
| `warmup` | how much history it needs before it answers |
| `uses_price` | whether it reads the market's own price (F7: it is labelled, and its skill is judged as a correction of the price) |
| `references` | the published sources it follows |
| `licence` | the licence of the data or method, where one applies |

A signal is wrapped as a forecaster (`SignalForecaster`), so the backtest,
the paper loop and a strategy use it unchanged; its forecasts are memoised
on the platform like every statistical forecaster's.

## The Gates

- **Purity** (an AST scan of the signal's module): imports only `math`,
  `statistics`, `numpy`, `dataclasses`, `typing`, `collections`,
  `datetime`'s types and `vp.signals`/`vp.forecast` names; no `open`,
  `eval`, `exec`, `compile`, `__import__`, `input`, no `os`, `sys`,
  `socket`, `requests`, `urllib`, `subprocess`, `time`, `random` and no
  attribute on them; no `datetime.now` or `date.today`. A signal reads the
  world only through the evidence object it is handed.
- **Cutoff sentinel**: every signal is computed on fixtures twice, once on
  the fixtures and once with sentinel rows added after the cutoff (results,
  scores, highs, later prices) whose values would move any estimate; the
  outputs must be identical. And a value computed at a cutoff must not
  change when the fixtures gain rows after that cutoff, which is the same
  test seen from the other side. Both run for every registered signal in
  CI.
- **Registry**: signals register by id in `vp/signals/registry.py`, loaded
  on first use; `vp signals list` prints the manifest (id, meta, the
  module's hash).

## New Evidence, All Cutoff-Bounded

- `scores(domain)`: final scores of matches settled before the cutoff,
  read from the venue's own resolved exact-score markets (exactly one per
  match resolves Yes, like a temperature bucket). Football only; available
  where the venue listed exact scores (2025-26 on).
- `event_prices(market)`: the prices at the cutoff of the other markets of
  the same event, with every label removed (a sibling's outcome is after
  the cutoff).
- `settled_prices(domain, hours)`: for markets settled before the cutoff,
  the price each had `hours` before its own settlement and its label; what
  a calibration layer is fitted on.

## The Initial Library (task 64)

| Id | Domains | What | References |
| :--- | :--- | :--- | :--- |
| `elo` | match domains | Elo from settled results, home advantage for football | Elo (1978), *The Rating of Chessplayers*; Hvattum and Arntzen (2010), *Int. J. Forecasting* 26 |
| `glicko2` | match domains | Glicko-2 ratings with rating deviation and volatility, one rating period per result | Glickman (2012), *Example of the Glicko-2 system* |
| `bradley_terry` | match domains | Bradley–Terry strengths with a home term, fitted by the MM algorithm on results before the cutoff, draws as half | Bradley and Terry (1952), *Biometrika* 39; Hunter (2004), *Annals of Statistics* 32 |
| `map_elo` | CS2 map winners | Elo on map results only | as `elo` |
| `poisson` | football: match, total, team total, both teams to score, exact score | independent Poisson goals with attack and defence strengths and a home factor, from final scores before the cutoff; prices the props from the same score grid | Maher (1982), *Statistica Neerlandica* 36 |
| `dixon_coles` | as `poisson` | Poisson with the low-score correction and time decay | Dixon and Coles (1997), *Applied Statistics* 46 |
| `climatology` | weather buckets | the bucket's frequency in the same season in earlier years | Wilks (2011), *Statistical Methods in the Atmospheric Sciences*, ch. 7 |
| `persistence` | weather buckets | tomorrow like the last observed day, spread by the city's day-to-day change | Wilks (2011), ch. 7 |
| `bucket_normalised` | weather buckets | the bucket's price divided by the sum of its event's bucket prices at the cutoff (a negative-risk event's prices must sum to one) | cross-market consistency; uses the price |
| `platt_market` | all | the market price through a logistic calibration fitted on the domain's settled markets before the cutoff, refitted as they grow | Platt (1999); the favourite-longshot bias, Snowberg and Wolfers (2010), *J. Political Economy* 118 |
| `isotonic_market` | all | the same with isotonic regression (pool-adjacent-violators) | Zadrozny and Elkan (2002), KDD |

Not in version 1, and why: pi-ratings need goal margins beyond the
exact-score window; NWP ensembles wait for Phase 17's archive; rest days
and roster flags are not probabilities; spread and depth imbalance need
the book at the cutoff, which backtests do not have; holders concentration
needs the venue's analytics endpoints, not yet collected.

A signal is listed on the Signals page only with its bench result.

## The Bench (task 65)

`vp signals bench --domain <d> [--window 2025-01..2026-09] [--hours 24]`
forecasts every applicable signal and the market on the domain's settled
markets in the window at the cutoff, pairs each signal with the market on
the markets that signal answered (so each comparison is on the same
markets), and reports per signal:

- the mean Brier difference against the market with a paired bootstrap 95%
  interval (market minus signal: positive is better than the market), the
  Brier skill, calibration (reliability, resolution, ECE);
- **alive** (interval above zero), **at par** (interval includes zero) or
  **anti** (interval below zero);
- the power statement: the markets the observed difference would need;
- the same per quarter, to show decay.

Results are written as JSON (`<root>/signals/bench/<domain>.json`) with the
command, the dataset version and each signal's module hash, so one command
reproduces any number; the platform keeps the latest per domain and the
Signals page draws them.

## Blends (task 66)

A blend is a logistic regression of the outcome on the logit of the market
price and of each chosen signal, fitted walk-forward: at each cutoff only
on markets settled before it, refitted when a month of new settlements has
arrived, with a small ridge penalty so a short history cannot produce wild
weights. It is scored only on markets after its fit, which the bench
enforces by construction. Blends are named `blend:<a>+<b>` and are the
strongest baseline a committee must beat.

## Committees (task 67)

Role forecasters (base-rate analyst, evidence analyst, market analyst, red
team, aggregator) behind the `Forecaster` interface, as a small DAG:
analysts answer independently from the evidence object and the domain
pack; the red team reads their answers and argues against the likeliest
mistake; the aggregator is not a model but a rule. Presets are YAML
(`vp/signals/committees/*.yaml`), platform copies versioned by hash.
Aggregation rules are data: mean of log-odds, trimmed mean, extremising
with a factor fitted on settled markets before the cutoff, and capping away
from 0 and 1. Every worker's answer, cost and rationale hash are stored
with the forecast. A committee is offered as a default only after it beats
single elicitation and the best blend on matched samples; until the first
keyed runs (Phase 15, task 60), committees exist and are tested against a
fake model, and are not offered.

## Contamination (task 68)

Every configuration that uses a model records the model's training cutoff
(`vp/forecast/llm.py`, `TRAINING_CUTOFFS`). Benches and run cards split
results at that date and count only markets settled after it as skill. A
model whose cutoff is not recorded is treated as contaminated over the
whole window: none of its results count as skill until the cutoff is
recorded from the provider's published model information.

## The Public Benchmark (task 69)

Weekly, on Monday at 00:00 UTC, the platform freezes a question set: up to
50 open markets across the domains, drawn with a published seed from those
with a price and a scheduled end within 30 days. For each platform
configuration (the market, each alive signal, each blend, later each
committee) and each opted-in strategy, the forecasts are written, and only
their commitment is published: the SHA-256 of the canonical forecast JSON
and a random salt. When the week's markets resolve, the forecasts and salts
are revealed, anyone can check them against the commitments, and they are
scored by Brier, log score and skill against the market with intervals. No
ranking is shown below 50 settled questions for a configuration.

## Contribution Checklist (task 70)

`vp signals check <module>` runs what a new signal must pass before it is
listed: the purity gate, the cutoff sentinel, complete metadata (every
field above), a reference for the method, a licence note for any data it
needs, and a bench result on at least one domain attached to the proposal.
The same checklist serves workspaces now and the community later (Phase 18,
with the Developer Certificate of Origin, F11).

## Where It Lives

`vp/signals/`: `base.py` (contract, meta, forecaster adapter), `gates.py`,
`registry.py`, `ratings.py`, `goals.py`, `weather.py`, `market.py`,
`bench.py`, `blend.py`, `committee.py` and `committees/`, `benchmark.py`;
new evidence accessors in `vp/forecast/evidence.py`; the command line
`vp signals list|check|bench`; on the platform, the bench and benchmark
jobs and the Signals page.
