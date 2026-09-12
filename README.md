# vibe-predict

An LLM forecaster for binary prediction-market contracts on Polymarket, scored
by backtest against resolved markets and then by paper trading, with live
execution planned but gated on a security design. Domains: Counter-Strike 2
esports, weather, and English Premier League football.

This repository continues from an earlier project that compared Polymarket and
Kalshi prices; that code is preserved unchanged under
[`archive/prediction_markets/`](archive/prediction_markets/README.md).

## Directory Structure

```ascii
prediction_markets/
├── vp/                        # the vibe-predict package (import name `vp`)
│   ├── cli.py                 # `vp build-dataset`, `vp snapshot`
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
│   └── backtest/
│       └── bankroll.py        # bankroll statistics over per-bet P&L
├── docs/                      # documentation (see index below)
├── tests/
│   ├── reports/               # test reports with runtimes
│   ├── test_bankroll.py       # bankroll arithmetic on a hand-checked sequence
│   ├── test_polymarket.py     # resolution ladder on fixture payloads
│   ├── test_domains.py        # membership and parsing on recorded questions
│   ├── test_schema_store.py   # record labels and Parquet round trip
│   └── test_dataset.py        # dataset and snapshot against a fake source
├── archive/
│   └── prediction_markets/    # the original project, unchanged
├── NOTICE                     # attribution and licence for ported code
├── PROJECT_PLAN.md            # phased roadmap with status tags
├── pyproject.toml             # uv project, ruff and ty configuration
└── .pre-commit-config.yaml    # ruff, ty and detect-secrets hooks
```

## Documentation

- [Documentation index](docs/index.md)
- [Architecture](docs/architecture.md): package layout, data flow and design decisions.
- [Data layer](docs/data_layer.md): market record, domain adapters, dataset and snapshots.
- [Provenance](docs/provenance.md): code adapted from Vibe-Trading and how it was changed.
- [Project plan](PROJECT_PLAN.md): phases, tasks and their status.
- [Archived project](archive/prediction_markets/README.md)

## Overview

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

## Getting Started

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                     # create the environment and install `vp`
uv run pre-commit install   # ruff, ty and detect-secrets on every commit
uv run vp --version
```

Quality checks, as run by the hooks:

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run detect-secrets scan --baseline .secrets.baseline
uv run pytest
```

Building data. Neither command needs credentials; `data/` is git-ignored.

```bash
uv run vp build-dataset --domain epl --max-markets 20   # quick retrievability check
uv run vp build-dataset --domain cs2 weather epl        # full resolved dataset
uv run vp snapshot --domain cs2 weather epl --depth 5   # one snapshot of open markets
```

Reading Polymarket needs no credentials. Requests to each host are spaced by
0.35 s by default; set `VP_POLYMARKET_MIN_INTERVAL` (seconds) to change it.

```python
from vp.venues import polymarket

hits = polymarket.search_events("premier league", limit=5, status="open")
event = polymarket.fetch_event(hits["events"][0]["event_id"])
market = polymarket.fetch_market(event["markets"][0]["market_id"], depth=5)
print(market["question"], market["resolution"]["state"])
```

## References

<span id="ref-gneiting-2007">[1]</span> Gneiting, T. and Raftery, A. E. (2007). *Strictly proper scoring rules, prediction, and estimation.* Journal of the American Statistical Association, 102(477), 359–378. [Link](https://doi.org/10.1198/016214506000001437)

<span id="ref-kelly-1956">[2]</span> Kelly, J. L. (1956). *A new interpretation of information rate.* Bell System Technical Journal, 35(4), 917–926. [Link](https://doi.org/10.1002/j.1538-7305.1956.tb03809.x)
