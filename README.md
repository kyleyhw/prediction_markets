# vibe-predict

A platform for building forecasting strategies for prediction markets, scoring
them honestly against the market's own price, and running them.

A binary Polymarket contract pays 1 if an event happens and 0 if it does not,
so its price is the market's probability of that event. Beating that price is
the whole difficulty, and the platform is built to measure whether a strategy
does: it supplies the data, evidence that cannot see past a forecast's cutoff,
strictly proper scoring, a backtest, paper trading and a dashboard. The honest
headline so far is that no baseline beats the market — weather climatology
scores −0.19 against it, EPL Elo −0.02, CS2 Elo −0.12 — which is the bar a
strategy has to clear, not a result the project is trying to explain away.

## What state it is in

- **Today it is a command line.** The engine is built and tested: build a
  dataset, backtest forecasters against the market, paper trade against the
  real order book, read it all in a local dashboard. That is what
  [Using it](#using-it) walks through, and it needs Python and a terminal.
- **The hosted web app is being built.** An account, a browser, strategies
  described in conversation and no terminal anywhere: that is Phase 13 onward
  of [the plan](PROJECT_PLAN.md), designed in [docs/product.md](docs/product.md).
  The platform under it runs on one machine under Docker Compose
  (`deploy/compose.yaml`): email sign-in, the friendly interface, paper
  trading and backtests started from the page with their progress and
  cost, per-person storage in Postgres and an object store, a job queue
  with worker pools, one live market-data subscription for everyone, and
  metrics and alerts; and strategies of one's own, described in a
  sentence, read back exactly as they will run, previewed, backtested and
  paper traded, with a research assistant that states no figure it did not
  look up ([docs/strategies.md](docs/strategies.md)); and a library of
  tested signals, each benched against the market, with a weekly
  benchmark whose forecasts are sealed before the questions resolve
  ([docs/signals.md](docs/signals.md)); and an evidence archive read
  strictly up to each forecast's cutoff, with weather forecasts as they
  were issued at the station each market resolves on
  ([docs/evidence.md](docs/evidence.md)); and teams, public shares,
  comments, leaderboards ranked by skill, and briefs and notices sent by
  email, chat or webhook, with a read-only tool server for AI assistants
  ([docs/collaboration.md](docs/collaboration.md)); and a report card
  from a trader's own public record, with the rule that describes them
  ([docs/shadow.md](docs/shadow.md)); and portfolio risk, strategy
  health that pauses a strategy which stopped beating the market, and
  numbered criteria a person approves before anything could go live
  ([docs/portfolio.md](docs/portfolio.md))
  ([docs/platform.md](docs/platform.md),
  [docs/interface.md](docs/interface.md), measured in
  [the Phase 13 report](tests/reports/phase13_platform.md)). It is not
  deployed anywhere yet. When it is, it is how most people will use this,
  and this page will point at it.
- **Live execution is last, and gated.** Nothing in this repository can sign
  or send a real order, and nothing will until the hosted security design is
  agreed (Phase 22). Paper trading is play money against real prices.

## Using it

Everything happens through the `vp` command; the dashboard is a read-only view
of what those commands wrote to the data root.

The shortest path from a clean checkout to a scored forecast:

```bash
uv sync                                                 # environment
uv run vp build-dataset --domain epl --max-markets 30   # ~30 s, data on disk
uv run vp backtest --domain epl --forecasters market constant
uv run vp ui --root data                                # http://127.0.0.1:8765/
```

### 1. Install

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                     # create the environment and install `vp`
uv run vp --version
uv run pre-commit install   # contributors: ruff, ty and detect-secrets on commit
```

### 2. Build a dataset

Reading Polymarket needs no credentials. `build-dataset` walks a domain's
closed markets, keeps the ones carrying settlement evidence, fetches each
one's price history and prints a retrievability report.

```bash
uv run vp build-dataset --domain epl --max-markets 30   # a quick check, ~30 s
uv run vp build-dataset --domain cs2 weather epl        # the full resolved set
```

```text
domain: epl
markets seen (closed, in domain): 30
resolved with a label: 30
resolved but void or split (no label): 0
closed but pending (no settlement record): 0
histories fetched: 30 (empty: 0, errors: 0)
written: data/markets/epl/resolved.parquet
```

`--no-history` skips the per-market history requests, which is much faster but
leaves the backtest with no market price at the cutoff, so nothing can be
scored. Keep the histories for any domain you intend to backtest. Requests to
each host are spaced by 0.35 s; set `VP_POLYMARKET_MIN_INTERVAL` (seconds) to
change it.

`vp snapshot` is the open-market counterpart — one file per run, with book
depth, which is what paper trading fills against:

```bash
uv run vp snapshot --domain epl --depth 5
```

### 3. Backtest

Every resolved market is forecast at its settlement time minus
`--hours-before-close`, scored against the market's own price at that cutoff,
and run through the fill simulator.

```bash
uv run vp backtest --domain epl --forecasters market constant
```

```text
markets: 30 selected, 30 with a price at the cutoff, 30 forecast by every forecaster (scored)

| Forecaster | n | Brier | Log | Skill vs market | Reliability | Resolution | ECE | Cost USD |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | 30 | 0.1997 | 0.5593 | +0.0000 | 0.0634 | 0.0878 | 0.1309 | 0.00 |
| constant | 30 | 0.2500 | 0.6931 | -0.2522 | 0.0278 | 0.0000 | 0.1667 | 0.00 |

written: data/backtests/epl/20260920T054313Z
```

The run directory holds `summary.md` (the tables above), `results.json` (the
same numbers plus the series behind the figures), `forecasts.jsonl` (the
registry for the run) and three figures: the reliability diagram, the
cumulative Brier advantage over the market, and the equity curves.

Forecasters are `market`, `constant`, `climatology`, `elo` and `llm`; `market`
is the reference every other one is scored against. Sizing and cost
assumptions are flags: `--fee-rate`, `--half-spread`, `--min-edge`, plus
`--kinds` to restrict to one parsed market type and `--max-markets` to cut the
run short.

**Only markets that *every* named forecaster answered are scored**, so that the
comparison is on one common set. A forecaster that abstains therefore empties
the table rather than shrinking it — see the notes below.

### 4. The LLM forecaster

`llm` is the one forecaster that needs credentials and costs money. The client
is built from the environment by the official Anthropic SDK, so exporting a key
is all the setup there is:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run vp backtest --domain epl --forecasters market llm --max-markets 50
```

It defaults to `claude-opus-5`, and the USD cost of the run is printed in the
`Cost USD` column and stored with each forecast. The model is shown the
question, the domain's structured fields and the evidence tools, but
deliberately not the market price. It has never been run against the API from
this repository — the development container holds no key — so treat the first
keyed run as the experiment it is, and start with `--max-markets`.

### 5. Paper trading

The forward loop snapshots a domain's open markets, forecasts them at *now*,
sizes against the real touch of the book and records everything in a
hash-chained ledger. All state is replayed from that ledger, so a cycle can be
run on a schedule and stopped at any point.

```bash
uv run vp paper run --domain epl --forecasters market elo   # one cycle
uv run vp paper settle                                      # resolve open positions
uv run vp paper leakage --domain epl --backtest data/backtests/epl/<stamp>
```

`run` prints the counts for the cycle — markets snapshotted, of those parsed by
the domain, forecasts made and orders filled. Budget time for it: a cycle
fetches one order book per open market at the default 0.35 s spacing, and EPL
alone had 1,444 open markets on 2026-09-20, so the book requests are eight
minutes before anything is forecast. A fifteen-minute cap was not enough for
one uncapped EPL cycle to finish. `settle` looks up each open
position's market and writes a settlement entry for the ones the venue has
resolved. `leakage` compares the forward scores against a backtest's, which is
the check that the backtest is not quietly optimistic.

### 6. The dashboard

```bash
uv run vp ui --root data      # http://127.0.0.1:8765/
```

The same page as the hosted app, read-only over the data root and without
accounts: a home screen for a sample strategy, market cards from the latest
snapshot, the paper ledger, every backtest with its charts, and Learn, in a
Simple or a Detailed reading level. It writes nothing on the server, so it
can be started and stopped freely. See [the interface page](docs/interface.md).

### What lands in the data root

`data/` is git-ignored, so a fresh clone starts empty and every command above
rebuilds what it needs.

```ascii
data/
├── markets/<domain>/resolved.parquet    # the labelled resolved set
├── histories/<domain>/<market>.parquet  # price history per market
├── snapshots/<domain>/<stamp>.parquet   # open markets with book depth
├── backtests/<domain>/<stamp>/          # summary.md, results.json, forecasts.jsonl, figures
└── paper/ledger.jsonl                   # the hash-chained paper-trading ledger
```

### Things worth knowing before you run it

- **Elo needs a warm-up.** It only answers `match` markets and only once both
  sides have at least three prior results before the cutoff. On a 30-market
  slice it abstains on everything, and because only commonly-answered markets
  are scored the table comes back with `n = 0`. Build the full domain dataset
  before backtesting Elo.
- **`vp paper run --max-markets N` caps the snapshot, not the parsed markets**,
  so a small `N` can leave nothing to forecast: `--max-markets 10` on EPL gave
  `{'snapshot': 10, 'parsed': 0, 'forecasts': 0, 'orders': 0}`. Raising `N`
  costs a book request each, so there is no quick way to run one cycle today.
- **A few order books return 404** during snapshots; the collector warns per
  market and carries on, and the snapshot is still written.
- **No baseline beats the market** (weather climatology skill −0.19, EPL Elo
  −0.02, CS2 Elo −0.12, measured in Phase 9). That is the benchmark a strategy
  is measured against, not a result the project is trying to fix.
- **The Phase 9 backtests ran fee-free.** The venue charges takers on sports
  and weather markets; pass `--fee-rate` until the baselines are re-run
  fee-aware.

### Using it as a library

The venue client is importable on its own and needs no credentials:

```python
from vp.venues import polymarket

hits = polymarket.search_events("premier league", limit=5, status="open")
event = polymarket.fetch_event(hits["events"][0]["event_id"])
market = polymarket.fetch_market(event["markets"][0]["market_id"], depth=5)
print(market["question"], market["resolution"]["state"])
```

## Documentation

- [Documentation index](docs/index.md)
- [Architecture](docs/architecture.md): package layout, data flow and design decisions.
- [Data layer](docs/data_layer.md): market record, domain adapters, dataset and snapshots.
- [Forecasters](docs/forecasters.md): contract, cutoff-bounded evidence, baselines, Elo, the LLM forecaster.
- [Scoring](docs/scoring.md) and [sizing](docs/sizing.md): proper scores, calibration, fees, Kelly.
- [Paper trading](docs/paper_trading.md): ledger, forward loop, settlement, leakage check.
- [Product design](docs/product.md): the hosted app for everyone, Phases 13 to 23.
- [Platform](docs/platform.md): configuration, tenancy, storage, jobs, the
  market-data service, budgets, observability and the local stand-in.
- [Collaboration and delivery](docs/collaboration.md): teams, shares, comments, leaderboards, channels, briefs, webhooks, the MCP server.
- [Shadow forecaster](docs/shadow.md): learning from your own public record.
- [Portfolio and health](docs/portfolio.md): risk across strategies, health checks, the promotion protocol.
- [Runbook](docs/runbook.md): what each alert means and what to do.
- [Scaling](docs/scaling.md): the multi-user architecture and capacity model.
- [Vibe-Trading review](docs/vibe_trading.md): the reference implementation, its collaborative tools, the capability mapping, non-infringement rules.
- [Documentation site](docs/site.md): the public site's structure and default visual style.
- [Interface](docs/interface.md): the browser app, its two reading levels, words and accessibility.
- [Browser dashboard](docs/ui.md): the Phase 12 page the interface grew from.
- [Security design](docs/security.md): proposed gate for live execution.
- [Provenance](docs/provenance.md): code adapted from Vibe-Trading and how it was changed.
- [Project plan](PROJECT_PLAN.md): phases, tasks and their status.
- [Archived project](archive/prediction_markets/README.md)

## The mathematics

A Polymarket contract on outcome $A$ is a token paying 1 if $A$ occurs and 0
otherwise, so its price $q \in (0,1)$ is the market's implied probability of
$A$. The project asks whether a language model, given only information
available before a cutoff time $t$, can produce a probability $\hat p$ that
beats $q$ as a forecast, and whether that edge survives fees and sizing.

Forecasts are judged with strictly proper scoring rules, for which reporting
one's true belief is the unique optimum [[1]](#ref-gneiting-2007). For outcome
$y \in \{0,1\}$,

$$\text{Brier}(\hat p, y) = (\hat p - y)^2, \qquad
\text{Log}(\hat p, y) = -\bigl[y \ln \hat p + (1-y)\ln(1-\hat p)\bigr].$$

The market price is the baseline forecast; skill is a mean score better than
the market's over the same markets. Position size follows the Kelly criterion
[[2]](#ref-kelly-1956): for a contract bought at price $q$ with belief
$\hat p$, the growth-optimal fraction of bankroll is

$$f^{*} = \frac{\hat p - q}{1 - q},$$

which is scaled down in practice. Derivations, the fee model and the
calibration decomposition are added to `docs/` by the phases that implement
them.

The pipeline is: venue client and data layer (done) → forecasters with an explicit cutoff → backtest scoring and fill simulation →
paper trading → security-gated live execution. The
[architecture page](docs/architecture.md) explains each stage and the reasoning
behind the main design choices, in particular why a closed market is never
treated as resolved without settlement evidence.

## Repository layout

This repository continues from an earlier project that compared Polymarket and
Kalshi prices; that code is preserved unchanged under
[`archive/prediction_markets/`](archive/prediction_markets/README.md).

<details>
<summary>The full tree</summary>

```ascii
prediction_markets/
├── vp/                        # the vibe-predict package (import name `vp`)
│   ├── cli.py                 # `vp build-dataset`, `vp snapshot`, `vp backtest`, `vp paper`, `vp ui`
│   ├── venues/
│   │   ├── _http.py           # throttled HTTP GET
│   │   └── polymarket.py      # read-only Polymarket client
│   ├── domains/               # cs2, weather, epl: membership and parsers
│   ├── markets/
│   │   ├── schema.py          # BinaryMarket record
│   │   ├── polymarket.py      # typed source: discovery, books, history
│   │   ├── store.py           # Parquet read and write
│   │   ├── dataset.py         # resolved-market dataset and report
│   │   └── snapshot.py        # snapshots of open markets
│   ├── forecast/
│   │   ├── base.py            # Forecast, Forecaster protocol
│   │   ├── evidence.py        # cutoff-bounded evidence (the look-ahead safeguard)
│   │   ├── baselines.py       # market price, constant, climatology
│   │   ├── stats.py           # Elo
│   │   ├── llm.py             # the LLM forecaster (Claude, tools, structured output)
│   │   └── registry.py        # append-only forecast registry
│   ├── backtest/
│   │   ├── scoring.py         # Brier, log, skill, reliability, Murphy decomposition
│   │   ├── sizing.py          # fees, edge, Kelly
│   │   ├── simulate.py        # fill-and-settle simulator
│   │   ├── run.py             # the backtest runner and its report
│   │   └── bankroll.py        # bankroll statistics over per-bet P&L
│   ├── paper/
│   │   ├── ledger.py          # hash-chained append-only ledger
│   │   ├── loop.py            # forward cycle and settlement
│   │   └── leakage.py         # forward-versus-backtest check
│   ├── live/                  # safety layer only; no signing until the design is agreed
│   │   ├── mandate.py         # fail-closed guard over hard caps
│   │   └── controls.py        # kill switch, environments, approvals, keyring
│   └── ui/
│       ├── server.py          # read-only JSON API over the data root
│       └── static/            # the dashboard page and vendored fonts
├── docs/                      # documentation (see index below)
├── tests/
│   ├── reports/               # test reports with runtimes, one per phase
│   ├── test_bankroll.py       # bankroll arithmetic on a hand-checked sequence
│   ├── test_polymarket.py     # resolution ladder and catalogue walk on fixtures
│   ├── test_domains.py        # membership and parsing on recorded questions
│   ├── test_schema_store.py   # record labels and Parquet round trip
│   ├── test_dataset.py        # dataset and snapshot against a fake source
│   ├── test_forecast.py       # evidence cutoff rule, baselines, Elo, registry
│   ├── test_llm.py            # LLM elicitation loop against a fake client
│   ├── test_scoring.py        # scores and the Murphy identity
│   ├── test_sizing.py         # fees and Kelly
│   ├── test_simulate.py       # fills and compounding
│   ├── test_backtest.py       # the runner end to end
│   ├── test_ledger.py         # chain integrity and tamper detection
│   ├── test_paper.py          # forward cycle, settlement, leakage
│   ├── test_live_guard.py     # every refusal path of the live safety layer
│   └── test_ui.py             # dashboard endpoints against the fixtures
├── archive/
│   └── prediction_markets/    # the original project, unchanged
├── NOTICE                     # attribution and licence for ported code
├── PROJECT_PLAN.md            # phased roadmap with status tags
├── pyproject.toml             # uv project, ruff and ty configuration
└── .pre-commit-config.yaml    # ruff, ty and detect-secrets hooks
```

</details>

## Developing

```bash
uv run pytest -q                                          # the offline test suite
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run detect-secrets scan --baseline .secrets.baseline
```

The tests are offline: no command in the suite touches the network, and
`tests/reports/` carries a report per phase with what was measured live.

## Licence

MIT, see [LICENSE](LICENSE). Code adapted from other projects and the
bundled fonts carry their own notices in [NOTICE](NOTICE).

## References

<span id="ref-gneiting-2007">[1]</span> Gneiting, T. and Raftery, A. E. (2007). *Strictly proper scoring rules, prediction, and estimation.* Journal of the American Statistical Association, 102(477), 359–378. [Link](https://doi.org/10.1198/016214506000001437)

<span id="ref-kelly-1956">[2]</span> Kelly, J. L. (1956). *A new interpretation of information rate.* Bell System Technical Journal, 35(4), 917–926. [Link](https://doi.org/10.1002/j.1538-7305.1956.tb03809.x)
