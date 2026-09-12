# Architecture

`vibe-predict` forecasts binary Polymarket contracts with a large language
model and scores those forecasts, first against resolved markets in a backtest,
then forward in paper trading, and only after an agreed security design in live
execution. This page describes the package layout as of Phase 6 and the data
flow the later phases fill in. The development sequence itself is in the root
[PROJECT_PLAN.md](../PROJECT_PLAN.md).

## Package Layout

```ascii
vp/
├── cli.py            # `vp build-dataset`, `vp snapshot`
├── venues/
│   ├── _http.py      # per-host throttled GET with session reuse
│   └── polymarket.py # read-only Gamma + CLOB client with resolution ladder
├── domains/
│   ├── base.py       # Domain: membership rules and question parser
│   ├── cs2.py, weather.py, epl.py
├── markets/
│   ├── schema.py     # BinaryMarket record
│   ├── polymarket.py # PolymarketSource: typed discovery, books, history
│   ├── store.py      # Parquet schemas, read and write
│   ├── dataset.py    # resolved-market dataset and retrievability report
│   └── snapshot.py   # append-only snapshots of open markets with books
└── backtest/
    └── bankroll.py   # equity curve, drawdown, permutation, bootstrap, walk-forward
```

## Data Flow

The pipeline the plan builds, with the phase that lands each stage:

1. **Venue client** (Phase 6, done). `vp.venues.polymarket` fetches events,
   markets, order books and price histories from Polymarket's public
   endpoints, and derives a settlement state from resolution evidence only.
2. **Market record and domain adapters** (Phase 7, done). A typed record
   for a binary contract, domain adapters that select CS2, weather and EPL
   markets and parse each question, a resolved-market dataset with price
   histories, and append-only snapshots of open markets. Details in the
   [data layer](data_layer.md) page.
3. **Forecasters** (Phase 8). Given a market and an explicit information
   cutoff $t$, a forecaster returns $\hat p \in (0,1)$ using only information
   available before $t$. The LLM forecaster is the central one; market price
   and simple statistical models are baselines.
4. **Scoring and backtest** (Phase 9). Proper scoring rules, calibration,
   edge after fees, Kelly sizing, and a fill simulator that settles each bet to
   0 or 1. `vp.backtest.bankroll` supplies the bankroll statistics.
5. **Paper trading** (Phase 10) and **live execution** (Phase 11, gated).

## Design Decisions

**Polymarket only.** The archived project targeted Polymarket and Kalshi.
Kalshi is deferred: one venue keeps the record, fee model and execution path
singular, and Polymarket's public endpoints need no credentials for reads.

**Closed is not resolved.** The client keeps a lifecycle `status` and a
separate `resolution` block, and only two pieces of evidence establish a
winner: the CLOB `winner` flag, or a final oracle status. A price pinned near 1
on a closed market is reported as an inference, never as the result. This
matters because scoring a forecast against a wrongly inferred outcome corrupts
every downstream statistic, and the upstream project measured that pinned
prices occur on more than a quarter of *open* markets.

**The first outcome is the event.** Every record fixes its first outcome as
the event whose probability is forecast, so $\hat p$, $q$ and $y$ always
refer to the same side. Markets without exactly two outcomes are excluded.

**Explicit information cutoff.** Every forecaster receives $t$ as an argument
and every data access is filtered to before it. This is the look-ahead
safeguard; the backtest and the forward paper-trading scores are later compared
per forecaster, and a gap between them is the diagnostic for leakage.

**Per-bet statistics.** Bets have no fixed time base, so the bankroll module
works in settlement order and reports a Sharpe-like ratio per bet without
annualisation. Randomised tests take an explicit seed.

**Throttling.** Both Polymarket hosts are rate-limited by source address with
no published limits. Requests to each host are spaced by a minimum interval
with jitter, defaulting to the spacing the upstream project found safe, and
overridable through `VP_POLYMARKET_MIN_INTERVAL`.

## Tooling

`uv` manages the environment, `ruff` lints and formats, `ty` type-checks with
every diagnostic blocking, and `detect-secrets` guards commits; all three run
as pre-commit hooks. The archive is excluded from linting and type checking.
