# Plan: Vibe-Backtesting for Prediction Markets

> **Status**: proposal, 2026-09-09. Nothing in this document is implemented yet.
> It answers three questions: what a "Vibe-Trading for prediction markets" looks
> like, how much of this repository carries over, and whether to keep this repo.

## 0. Summary

**Goal.** Type a category (`weather`), pull every relevant market plus its price
history and resolution from Polymarket and Kalshi, describe a strategy in plain
English, and get a backtest report back. Same loop as
[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (prompt -> data
loader -> generated strategy code -> engine -> run card), but built around the
things that make prediction markets different: contracts settle to 0 or 1, the
tradable universe is thousands of short-lived markets rather than a fixed ticker
list, and the edge usually comes from an external signal (a weather forecast)
compared against the market's implied probability.

**Fit with the current repo.** About a third of what is needed exists in a
directly reusable form: the two venue clients, the `MarketEvent` model, the
category config, the order-book walk in `calculate_metrics.py`, the tooling
(uv, ruff, ty, pre-commit) and the API documentation. The remaining two thirds
are new: a storage layer, historical ingestion with resolutions, a settlement
aware engine, a strategy interface, and the LLM layer. Nothing that matters has
to be thrown away, but the code needs to be reorganised from a pile of research
scripts into a package before it grows. Section 4 has the file-by-file verdict.

**Repo decision.** Keep this repository and evolve it in place. A GitHub rename
is cheap and reversible and can happen whenever the product name settles
(section 6). Starting fresh would only discard useful history and docs. Do not
fork Vibe-Trading (section 2.2).

**Recommended first slice.** Kalshi daily temperature markets, hold-to-settlement
strategies, a declarative strategy spec, and Claude Code driving the CLI through
an MCP server. That gives a working "vibe backtest" in roughly a week and
de-risks the historical data question before any engine sophistication.

## 1. What exists today

Facts established by reading the code and running the toolchain in a clean
container (the venue APIs themselves were unreachable from that sandbox, so live
behaviour is taken from the repo's own evidence and marked "verify" where it
matters).

### 1.1 Works and is worth keeping

| Piece | Where | Notes |
| :--- | :--- | :--- |
| Polymarket client | `src/collectors/polymarket.py` | Gamma `/events` with offset pagination and `tag_id`/`tag_slug`; CLOB `/book`; CLOB `/prices-history` (verified on active markets, plots in `plots/`). |
| Kalshi client | `src/collectors/kalshi.py` | `/markets?series_ticker=`; `/series/{s}/markets/{t}/candlesticks` with `start_ts`/`end_ts`/`period_interval`, paginated in 90-day chunks in `election_history.py`. `plots/election_2024_history.png` exists, which indicates candlesticks for a settled market (`PRES-2024-DJT`) worked at least once. |
| Normalised model | `src/collectors/base.py` | `MarketEvent` with best bid/ask, mid, spread, depth, token ids, tags, end date. |
| Category filter | `src/analysis/market_config.json`, `find_markets_by_category.py` | Keyword + tag + exclude lists per category. The "filter by type" feature already exists in embryo. |
| Fill math | `src/analysis/calculate_metrics.py` | `calculate_average_entry` walks a book for a target size. This is the core of a backtest fill model. |
| Domain knowledge | `docs/polymarket_metadata.md`, `docs/liquidity_analysis.md`, `docs/definitions.md` | Raw API payloads with field semantics; the finding that Polymarket's `liquidity` is a spread-scaled projection, not book depth. Directly relevant to fill modelling and capacity estimates. |
| Tooling | `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml` | `uv sync` works; `ty check` passes. |

### 1.2 Gaps and defects that shape the plan

- **No storage layer.** Every script fetches live and prints. `data/raw` and
  `data/processed` are described in the docs but do not exist. `.gitignore`
  ignores all `*.csv`, so nothing tabular can be checked in either.
- **Historical data for resolved markets is unsolved.** `PROJECT_PLAN.md`
  records 400/404 responses from Polymarket for the 2024 election history; the
  only closed-market series in the repo is a manual UI export
  (`data/raw/polymarket-price-data-*.csv`). Kalshi looks better (see above).
  This is the single biggest risk for backtesting and is the first thing to
  verify (section 7).
- **No resolutions.** Nothing records which outcome won. A backtest cannot
  settle positions without it.
- **The category filter is a substring match.** `reports/market_report_weather_*.md`
  lists 405 "weather" markets and the top hits are "Russia x Ukraine ceasefire"
  and "How to Train Your Dragon", because `rain` matches `Ukraine` and `Train`.
  It also downloads every active market on each run because filtering is
  client side.
- **Kalshi client is thin.** No `status` filter, no cursor pagination, no
  series discovery, no order book depth (it fabricates a one-level book from
  top of book), no `no` side quotes.
- **Polymarket client fetches a book per market by default** (`fetch_book=True`
  in `fetch_markets`), which is an N+1 request pattern. The Gamma
  `/prices-history` fallback in `fetch_price_history` is undocumented and
  probably dead code.
- **CLI is hardcoded to one 2025 CS2 tournament.** All six `pm` subcommands use
  the StarLadder slug and series ticker.
- **Tests are not tests.** `tests/test_collectors.py` hits live APIs and has
  no assertions. There is no CI (`.github/` is absent).
- **Docs drift.** `README.md` and `docs/architecture.md` reference
  `src/main.py`, `requirements.txt`, `investigate_kalshi.py`,
  `src/utils/matching.py` and `src/analysis/arbitrage.py`; none exist (only
  stale `.pyc` files remain for two of them).
- **Toolchain nits.** `ruff check` reports 7 errors and `ruff format --check`
  wants to reformat 2 files at HEAD, so the pre-commit hooks are not clean.
  `requires-python = ">=3.14"` while ruff targets `py312`; the import package
  is literally named `src` (`from src.collectors import ...`).
- **Legacy scripts.** Roughly 25 one-off probes in `src/analysis/`
  (`try_*`, `find_*`, `inspect_page_source.py`, `dump_all_markets.py`, ...)
  are research scratch, not library code.

## 2. What to borrow from Vibe-Trading, and why not to fork it

### 2.1 The pattern worth copying

Vibe-Trading's loop, from `agent/src/skills/strategy-generate/SKILL.md` and
`agent/backtest/runner.py`:

1. The agent parses the prompt into a validated `config.json` (pydantic schema:
   codes, dates, source, interval, engine, cash, warm-up).
2. The agent writes `code/signal_engine.py` implementing one small contract
   (`SignalEngine.generate(data_map) -> {code: Series in [-1, 1]}`).
3. A fixed runner (`python -m backtest.runner <run_dir>`) loads data through a
   loader registry with fallback chains, AST-scrubs the generated file, runs
   the engine in a subprocess, and writes artifacts plus a `run_card.json`
   (config hash, strategy hash, data sources, warnings).
4. Optional validation: Monte Carlo permutation, bootstrap Sharpe CI,
   walk-forward.
5. The agent reads `metrics.csv`, critiques, edits, reruns.

Everything in that list transfers. The generated-code contract, the run
directory as the unit of reproducibility, the loader registry, the AST guard
before importing LLM output, and the validation suite are all worth
re-implementing in miniature.

### 2.2 Why not fork or extend Vibe-Trading itself

- It is about 400k lines of Python plus a React/Electron front end, built on
  LangChain/LangGraph, FastAPI, 27 data loaders, 14 broker connectors and a
  dozen chat-channel integrations. The prediction-market piece would be a few
  thousand lines inside that.
- Its loaders return OHLCV per symbol for a fixed `codes` list, and
  `BaseEngine` (2,300 lines) is a bar-by-bar weight allocator with shorting,
  forward-fill and margin. Settlement to 0/1, a universe that changes daily,
  and probability-space accounting do not fit; you would write a new engine
  anyway, inside someone else's release cadence.
- Its `agent/src/tools/prediction_market_tool.py` is a read-only Polymarket
  lookup tool (search, event, market, history). It is useful as a reference for
  field semantics, in particular its resolution logic, but it is not a loader
  or an engine.

Build standalone and lean, copy the patterns, and optionally expose the result
as an MCP server so Vibe-Trading or Claude Code can call it.

## 3. Target design

### 3.1 User workflow

```bash
# discovery
pm markets list --category weather --venue kalshi,polymarket --status open
pm markets search "highest temperature NYC" --status resolved --since 2025-06-01
pm categories show weather            # keyword/tag/series config, with hit counts

# data
pm data sync --category temperature --since 2025-01-01     # catalog + history + resolutions
pm data record --category temperature --every 5m           # forward snapshots incl. books
pm data status                                             # coverage table per venue/category/month

# backtest a saved strategy
pm backtest run strategies/forecast_edge.json --from 2025-06-01 --to 2025-08-31
pm backtest run strategies/my_strategy.py --category temperature --from ... --to ...

# vibe
pm vibe "buy the temperature bucket the forecast points to when it trades under 40c
         within 36h of close, hold to settlement, max $50 per market" \
        --category temperature --from 2025-06-01 --to 2025-08-31
pm report show runs/2025-09-09T12-00_forecast_edge
```

### 3.2 Package layout

Rename the import package from `src` to a real name (working name `pm`, matching
the CLI; change it once, early). Old research scripts move to `scripts/legacy/`.

```text
pm/
  cli/            markets, data, backtest, vibe, report subcommands
  catalog/        Category registry, discovery per venue, word-boundary filters
  venues/         Polymarket and Kalshi HTTP clients (session, retry, rate limit)
  models.py       Market, Outcome, Quote, BookSnapshot, PriceBar, Trade, Resolution
  store/          DuckDB + Parquet schema, upserts, point-in-time queries
  ingest/         backfill.py, recorder.py, sync.py, quality.py
  features/       point-in-time feature providers (market-derived, weather forecasts)
  backtest/       engine.py, portfolio.py, fills.py, fees.py, metrics.py,
                  strategy.py (protocol + spec DSL), runner.py, report.py
  vibe/           prompts, generate, validate, loop, library
  mcp_server.py   tools: list_markets, sync_data, run_backtest, get_report
strategies/       saved specs and code
runs/             run artifacts (gitignored)
data/             duckdb + parquet (gitignored)
tests/            pytest, recorded API fixtures
scripts/legacy/   the current one-off scripts, unchanged
```

### 3.3 Data model

Split `MarketEvent` into static and point-in-time parts. The current class mixes
metadata with a single quote, which is fine for a live scan and wrong for a
time series.

- `Market`: venue, market_id, event_id, question, rules text, our `category`,
  venue tags, `series` (Kalshi series ticker or Polymarket event slug family),
  outcomes with token ids or yes/no sides, open/close times, tick size, min
  order size, fee parameters, `neg_risk` (Polymarket multi-outcome), `resolution`.
- `Resolution`: winning outcome (or void / 50-50), resolved_at, evidence source.
- `Quote`: market, outcome, ts, bid, ask, last, mid. One row per observation.
- `BookSnapshot`: full depth at ts (only from the forward recorder or a live
  fetch; venues do not serve historical depth).
- `PriceBar`: historical series. Polymarket `prices-history` points (`t`, `p`)
  and Kalshi candlesticks (OHLC for price, yes_bid, yes_ask, volume, open
  interest, in cents scaled to [0, 1]).
- `Trade`: optional trade prints where a venue exposes them.

Categories become explicit per-venue identifiers rather than substrings:

```json
{
  "temperature": {
    "kalshi":     {"series_prefixes": ["KXHIGH", "KXLOW"], "category": "Climate and Weather"},
    "polymarket": {"tag_slugs": ["weather"], "title_regex": "\\b(highest|lowest) temperature\\b"},
    "exclude_regex": "\\b(vs\\.?|spread|over/under)\\b"
  }
}
```

Word-boundary regexes replace `in` substring tests; venue-side filters
(`tag_slug`, `series_ticker`, `category`) replace "download everything".

### 3.4 Historical data: sources, what is verified, what is not

This is the part that decides whether the project works, so it comes before the
engine in the roadmap.

**Kalshi**

| Need | Endpoint | Status |
| :--- | :--- | :--- |
| Enumerate settled markets | `GET /markets?series_ticker=&status=settled&limit=1000&cursor=` (`min_close_ts`/`max_close_ts` per docs) | `status` used in `find_kalshi_history.py`; cursor paging and the timestamp filters need verifying. |
| Series discovery | `GET /series?category=...`, `GET /series/{ticker}` | Not used yet; verify the exact category label for weather. |
| Price history | `GET /series/{s}/markets/{t}/candlesticks?start_ts&end_ts&period_interval=1|60|1440` | Verified in repo for active and, by the election plot, at least one settled market. |
| Resolution | market object `result` (`yes`/`no`) once `status == settled` | Verify field names on a settled weather market. |
| Trades, current book | `GET /markets/trades`, `GET /markets/{t}/orderbook` | Public per docs; verify. |
| Fees | published schedule, general form `0.07 * contracts * P * (1 - P)` per side, rounded up, with series-specific rates and maker rebates | Verify the current schedule; fees are quadratic in P and matter for weather buckets priced near 0.1-0.3. |

**Polymarket**

| Need | Endpoint | Status |
| :--- | :--- | :--- |
| Enumerate closed markets | Gamma `GET /events?closed=true&tag_slug=&limit=&offset=` (date-window params per docs) | Offset paging verified; check whether `closed=true` listings are complete for older months. |
| Price history | CLOB `GET /prices-history?market=<token_id>&interval=max|1m|1w|1d|6h|1h&fidelity=<minutes>` | Verified on active markets. Reported 400/404 for the 2024 election in `PROJECT_PLAN.md`. Vibe-Trading's tool documents the same endpoint without a closed-market caveat. **Test on 20+ recently resolved temperature markets and record success rate by market age.** |
| Resolution | CLOB `GET /markets/{conditionId}` -> `tokens[].winner`; Gamma `umaResolutionStatus in {resolved, settled}` | Per Vibe-Trading's field notes (read off live responses). `closed == true` alone is not settlement; pinned prices are not settlement. Adopt those rules. |
| Trades | `data-api.polymarket.com/trades?market=<conditionId>` | Undocumented in this repo; verify. |
| Fees | Most markets fee-free historically; fee-enabled markets expose per-market fee fields on the CLOB market object | Read them per market; verify the formula. |
| Bulk backfill | Goldsky subgraph, Dune | Optional, only if the CLOB endpoint proves unreliable for resolved markets. Manual UI CSV export is the last resort. |

**Weather signal (the external feature)**

- Both venues run daily "highest/lowest temperature in {city} on {date}" events
  as mutually exclusive buckets, resolved against a named station reading
  (for example Central Park for NYC). Rules text names the station.
- Point-in-time forecasts, as issued, are required to avoid look-ahead. Open-Meteo's
  historical forecast / previous-runs API (free, no key, forecasts by issue time
  and lead) is the primary candidate; NOAA NBM/NDFD archives are the alternative.
  Verify coverage for the target cities and dates.
- Observed station values are only needed to sanity-check resolutions.

**Two ingestion modes** because backfill alone will never give order-book
depth: `sync` backfills catalog, price series and resolutions; `record` runs
forward on a timer capturing quotes and full books for open markets in the
chosen categories. Backtests over recorded periods use real depth; backtests
over backfilled periods use a modelled fill (3.5) and say so in the run card.

### 3.5 Engine semantics specific to prediction markets

- **Rolling universe.** At time `t` the universe is the set of markets with
  `open_time <= t < close_time` in the chosen categories, as they existed at
  `t`. Markets appear and disappear daily.
- **Clock.** Fixed step (hourly by default) or event-driven on new price
  points. The strategy sees quotes and features `as of t` only.
- **Positions are long tokens only.** Buy YES or buy NO (Polymarket has explicit
  NO tokens; Kalshi has a no side). Selling means selling tokens you hold. No
  margin, no shorting.
- **Settlement.** At `resolved_at` each held share pays 1 or 0 (0.5 on a void
  resolution). Hold-to-settlement is the default exit; early exit at a quoted
  price is optional.
- **Fills.** If a book snapshot exists at `t`, walk it with the existing
  `calculate_average_entry`. Otherwise fill at ask (or mid plus half a modelled
  spread) times `(1 + slippage_bps)`, capped by a participation limit such as
  a fraction of the volume traded in the window, so backfilled data cannot
  produce fantasy capacity. Every fill records whether it was book-based or
  modelled.
- **Fees** per venue, per market, from the parameters stored on `Market`.
- **Accounting.** Cash, positions with cost basis, mark-to-market on bid
  (conservative) or mid, realised and unrealised P&L, per-market attribution.
- **Leakage guards** as assertions, not conventions: every feature carries an
  `as_of` timestamp that must be `<= t`; no quote newer than `t` is visible;
  resolutions are invisible before `resolved_at`.

### 3.6 Strategy interface

Two tiers, mirroring the choice between a declarative spec and generated code.

**Tier 1, declarative spec** (pydantic-validated JSON, executed by a rule
engine with a whitelisted expression evaluator, never `eval`):

```json
{
  "name": "forecast_edge_temp",
  "universe": {"venues": ["kalshi"], "category": "temperature", "min_liquidity_usd": 500},
  "schedule": "1h",
  "features": ["forecast_high_temp", "hours_to_close", "spread"],
  "entry": [{
    "when": "implied_prob(bucket_of(forecast_high_temp)) < 0.40 and hours_to_close < 36",
    "buy": "bucket_of(forecast_high_temp)"
  }],
  "sizing": {"type": "fixed_usd", "usd": 50, "max_open_markets": 20},
  "exit": {"type": "hold_to_resolution"},
  "risk": {"max_total_exposure_usd": 1000}
}
```

Most weather, favourite/longshot, mean-reversion and cross-venue arbitrage
ideas fit this tier, and it is cheap for an LLM to produce correctly and easy
to diff between iterations.

**Tier 2, Python** for anything the DSL cannot express:

```python
class Strategy(Protocol):
    name: str
    def decide(self, views: list[MarketView], portfolio: PortfolioView, ctx: Context) -> list[Order]: ...
```

`MarketView` bundles the market, latest quotes per outcome, features, and time
to close. `Context` exposes `ctx.now`, `ctx.params`, `ctx.feature(market, name)`
and logging. Generated files are AST-checked (import whitelist: `numpy`,
`pandas`, `math`, `datetime`, `pm.backtest.api`; no I/O, no network, no
`__main__`), linted, type-checked, dry-run on a few days of data, then run in a
subprocess with a timeout.

### 3.7 The vibe layer

**Front end A, MCP first.** Expose `list_markets`, `sync_data`, `run_backtest`
(spec or code), `get_report` and `list_strategies` through a small FastMCP
server, as Vibe-Trading does with `vibe-trading-mcp`. Claude Code or Claude
Desktop then is the agent: it reads the strategy contract from a `SKILL.md`,
writes the spec or code, calls the tools, reads the report, iterates. This is
about a hundred lines and needs no LLM integration code, so it is the right
first version of "backtest by vibe describing it".

**Front end B, built-in `pm vibe`.** A self-contained loop using the
`anthropic` Python SDK with `claude-opus-5` (adaptive thinking on by default,
`output_config.effort` set to `high` for code generation) and structured
outputs (`client.messages.parse` against the `StrategySpec` pydantic model) so
the spec never needs hand-parsing. Steps: extract spec or code with an explicit
list of assumptions -> validate -> run -> have the model write a short critique
of the run card (concentration of P&L in a few markets, modelled-fill share,
capacity limits, guard triggers) and propose two or three variants -> persist
under `strategies/<slug>/`. Keep the provider behind one interface so the
model can be swapped. Generation cost is a few thousand tokens per iteration,
so it is negligible next to data collection.

### 3.8 Metrics, report, validation

- Returns: total P&L, ROI on deployed capital, per-market and per-day P&L,
  hit rate, realised edge versus price paid, max drawdown, exposure and
  turnover over time, fees paid.
- Prediction-market specific: Brier score and calibration plot of the
  strategy's own probability estimates when it provides them; P&L by implied
  probability bucket; P&L versus hours-to-close at entry.
- Capacity: rerun with the participation cap swept from 1% to 25% of window
  volume and plot P&L against it.
- Validation: bootstrap over resolved markets (they are the natural
  independent unit) for a confidence interval on ROI; walk-forward by date;
  parameter sensitivity grid.
- Every run writes `config.json`, the spec or code, a data snapshot hash,
  `metrics.json`, `trades.csv`, `equity.csv`, plots, `report.md` and
  `run_card.json`.

## 4. Compatibility: file-by-file verdict

| Current | Verdict | Becomes |
| :--- | :--- | :--- |
| `src/collectors/polymarket.py` | Keep, refactor | `pm/venues/polymarket.py`: shared session, retries, rate limiting, `fetch_book=False` default, closed-catalog paging, `fidelity`, resolution lookup, drop the Gamma history fallback. |
| `src/collectors/kalshi.py` | Keep, extend | `pm/venues/kalshi.py`: `status`, cursor paging, series discovery, orderbook, trades, no-side quotes. Candlesticks stay. |
| `src/collectors/base.py` | Split | `pm/models.py` (3.3). |
| `src/analysis/market_config.json`, `find_markets_by_category.py`, `find_weather_markets.py` | Keep the idea, replace the matching | `pm/catalog/` with per-venue identifiers and word-boundary regexes. |
| `src/analysis/find_liquid_markets.py` | Merge | `pm markets list --min-liq --min-vol --max-spread`. |
| `src/analysis/calculate_metrics.py` | Keep as-is | `pm/backtest/fills.py`. |
| `src/analysis/analyze_slippage.py` | Keep | A `pm report slippage` diagnostic. |
| `src/analysis/market_pipeline.py`, `docs/math_and_logic.md` matching section | Keep for later | Cross-venue matching for arbitrage strategies; not needed for the first slice. |
| `election_history.py`, `verify_history.py`, `plot_arbitrage_history.py` | Mine, then archive | They hold the verified call shapes (candle schema, 90-day chunking); lift those into the clients and tests. |
| `compare_starladder.py`, `plot_starladder.py`, `plot_kalshi_starladder.py`, `plot_spread_candles.py`, `analyze_blast_rivals.py` | Archive | Hardcoded to one tournament. `scripts/legacy/`. |
| `try_*`, `find_*`, `inspect_page_source.py`, `dump_all_markets.py`, `audit_apis.py`, `verify_tags.py`, `get_poly_details.py`, `verify_price_source.py` | Archive or delete | Research probes. |
| `src/utils/find_poly_tag.py` | Keep | `pm categories discover-tags`. |
| `src/utils/derive_poly_creds.py` | Keep, unused for now | Only needed for trading, which is out of scope. |
| `src/cli.py` | Rewrite | Subcommand tree in 3.1. |
| `src/config.py` | Keep | Credentials and env loading. |
| `docs/*` | Keep | Fix the drift listed in 1.2; `polymarket_metadata.md` and `liquidity_analysis.md` feed fill and capacity modelling. |
| `tests/test_collectors.py` | Replace | pytest with recorded JSON fixtures per endpoint; live-API tests behind a marker. |
| `pyproject.toml`, `uv.lock`, pre-commit | Keep | Fix the 7 ruff errors, add `pytest`, `pydantic`, `duckdb`, `pyarrow`, `anthropic`, `fastmcp`; add a GitHub Actions workflow for ruff, ty and pytest; decide the Python floor (7). |
| `plots/`, `reports/` | Keep as history | Future artifacts go to `runs/`, gitignored. |

## 5. Roadmap

Effort is in focused days. The first three phases are the vertical slice.

**Phase 0, restructure (1 day).** Rename the import package, move legacy
scripts, fix ruff, add pytest with fixtures and CI, fix README drift, replace
`print` with `logging`. Tag the current state first (`git tag v0.1-research`)
so the research era stays navigable.

**Phase 1, universe and filter (1-2 days).** Category registry with per-venue
identifiers, word-boundary matching, venue-side filters, `pm markets`
commands, catalog stored in DuckDB. Acceptance: `pm markets list --category
temperature` returns only temperature markets from both venues, with counts
that match a manual check, without downloading the whole catalog.

**Phase 2, historical ingestion (3-5 days).** Storage schema, Kalshi backfill
(settled markets, candlesticks, resolutions), Polymarket backfill (closed
events, `prices-history`, CLOB resolution evidence), forward recorder, coverage
report. Acceptance: `pm data status` shows, per venue and month, how many
temperature markets have a price series and a resolution; the Polymarket
closed-history success rate is measured, not assumed.

**Phase 3, engine and strategy API (4-6 days).** Models, portfolio, fills,
fees, settlement, metrics, report, run directory, `Strategy` protocol and the
spec DSL, runner with AST guard and subprocess isolation. Acceptance: four
hand-written baselines (buy favourite, buy longshot, forecast-edge with a stub
feature, cross-venue arbitrage) run reproducibly on three months of
temperature markets; unit tests on accounting with synthetic markets cover
settlement, void resolution, fees and the participation cap.

**Phase 4, features (2-3 days).** Feature store with `as_of` semantics,
market-derived features, Open-Meteo previous-runs provider keyed by city,
date and issue time, station mapping from rules text, leakage guards.
Acceptance: the forecast-edge baseline runs on real forecasts and the guard
test fails when a feature is deliberately timestamped in the future.

**Phase 5, vibe layer (2-4 days).** MCP server plus `SKILL.md` first; then
`pm vibe` with the Anthropic SDK, structured spec extraction, critique loop,
strategy library. Acceptance: ten natural-language descriptions produce
specs whose fields match an expected set, and each runs end to end.

**Phase 6, validation and reporting (2-3 days).** Bootstrap over markets,
walk-forward, sensitivity grid, capacity sweep, calibration plots, HTML
report.

**Later, out of scope for now.** Paper trading from the recorder, live
alerts, order execution through `py-clob-client` and the Kalshi API behind a
user-defined mandate (symbol allowlist, size caps, kill switch) the way
Vibe-Trading gates its broker connectors.

Roughly three to four weeks of focused work for a solid v1; about one week for
the vertical slice (Phases 0-3 on Kalshi temperature markets with the MCP
front end from Phase 5). Kalshi goes first because its settled-market
candlesticks and explicit `result` field are the lowest-risk historical data
in the repo's evidence; Polymarket joins once Phase 2 has measured its
closed-market history coverage.

## 6. New repo or rename this one?

**Keep this repo.** Three different names are in play and only one of them is
a repository rename:

| Name | Today | Change cost |
| :--- | :--- | :--- |
| GitHub repository | `kyleyhw/prediction_markets` | Trivial. Settings -> General -> Rename. GitHub redirects the old web URLs and old `git` remote URLs (clone, fetch, push) to the new name. Update local remotes anyway with `git remote set-url origin <new url>`. |
| Python distribution | `prediction-markets` in `pyproject.toml` | A one-line edit; only matters if you publish to PyPI. |
| Import package and CLI | `src` and `pm` | Real code churn (every import line). Do the import-package rename in Phase 0, once, before the codebase grows. The CLI name can stay `pm`. |

Things a GitHub rename does not fix automatically: hardcoded clone URLs in
docs and badges, GitHub Pages URLs, and the redirect itself breaks if you later
create a new repository under the old name. There are no GitHub Actions, Pages
or badges here today, so none of that applies yet. Renaming later, once the
product name settles, is fine.

Starting a new repository would only make sense to get a clean public history
or different ownership or licence. It would cost the 43 commits of context, the
API documentation, and the liquidity research, and buy nothing the
restructure in Phase 0 does not.

## 7. Verify before building

These could not be checked from the sandbox this plan was written in (its
egress policy blocks `gamma-api.polymarket.com` and `api.elections.kalshi.com`).
Each is a short script against the live APIs.

1. Polymarket CLOB `prices-history` on resolved markets: sample 20 or more
   temperature markets resolved 1 week, 1 month, 3 months and 6 months ago;
   record status codes and point counts per `interval`/`fidelity`.
2. Polymarket resolution evidence: confirm `tokens[].winner` on
   `/markets/{conditionId}` and `umaResolutionStatus` on the same sample.
3. Kalshi settled-market enumeration: `status=settled` with cursor paging and
   `min_close_ts`/`max_close_ts` for one temperature series over three months;
   confirm the candlestick coverage and the `result` field.
4. Kalshi series discovery: the exact `category` value for weather and the
   list of temperature series tickers.
5. Fee schedules on both venues as of today.
6. Open-Meteo previous-runs coverage for the target cities and 2025 dates.
7. Python floor: keep `>=3.14` only if `duckdb`, `pyarrow`, `pydantic`,
   `anthropic` and `fastmcp` all install cleanly on it; otherwise drop to
   `>=3.12` (the container used for this review had 3.11 and `uv` fetched
   3.14 itself, so it works, but wheel availability for new dependencies is
   the question).
8. Which LLM provider and keys to use for `pm vibe`; the MCP front end needs
   none.
