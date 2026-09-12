# Project Plan: Prediction Market Efficiency Analysis (CS2 & EPL)

## Phase 1: Data Acquisition
1.  [completed] Implement `PolymarketCollector` in `src/collectors/polymarket.py` using Gamma API (GraphQL/REST) to fetch markets by tag.
2.  [completed] Implement `KalshiCollector` in `src/collectors/kalshi.py` using V2 REST API to fetch markets by series ticker.
3.  [completed] Define standardized `MarketEvent` data model in `src/collectors/base.py` and implement JSON/CSV storage logic.

## Phase 2: Analysis & Visualization
1.  [completed] Implement fuzzy event matching utility in `src/utils/matching.py` using `difflib` to align events across platforms.
2.  [completed] Develop arbitrage analysis script in `src/analysis/arbitrage.py` to calculate spreads and identify risk-free opportunities.
3.  [completed] Create visualization scripts (`src/analysis/visualize.py`) to plot market counts and price discrepancies.

## Phase 3: Generalization & Multi-Sport Support
1.  [completed] Create configuration system in `src/config.py` to map categories (CS2, EPL) to platform-specific identifiers.
2.  [completed] Refactor `main.py` and collectors to iterate through configured categories and handle dynamic tagging.
3.  [pending] Finalize English Premier League (EPL) support by discovering the correct Kalshi series ticker and verifying event overlap.

## Phase 4: Historical Analysis (Current Focus)
1.  [completed] Verification of historical data access for closed markets (Polymarket Gamma/CLOB).
    *   Result: Closed/Settled markets (e.g., 2024 Election) return 400/404 errors via API, confirming archival/cold storage.
2.  [completed] CS2 Starladder Analysis.
    *   Fetches live/active history for Polymarket and Kalshi.
    *   Generates Arbitrage and Candlestick plots.
3.  [shelved] Authenticated Data Fetching for Kalshi.
    *   Pending user need for specific closed market data that requires auth.

## Phase 5: Documentation
1.  [completed] Document mathematical principles (odds derivation, arbitrage formulas) in `docs/math_and_logic.md`.
2.  [completed] Document system architecture (ETL pipeline, design patterns) in `docs/architecture.md`.
3.  [completed] Update `README.md` with ASCII directory tree, installation instructions, and documentation links.

## Future Extensions
1.  [pending] Build automated trading bot to execute arbitrage trades when opportunities exceed a defined threshold.
2.  [pending] Implement historical backtesting framework to analyze market efficiency improvements over time.
3.  [pending] Create web dashboard (Streamlit/Dash) to visualize live arbitrage opportunities and market spreads.

---

# Project Development Plan: vibe-predict

This section continues the plan above. Phases 1–5 describe the original
`prediction_markets` project, whose code is retained under `archive/` and is not
deleted. Phases 6 onward describe `vibe-predict` (distribution name
`vibe-predict`, import package `vp`, CLI command `vp`): an LLM forecaster for binary
prediction-market contracts on Polymarket in three domains, CS2 esports,
weather, and English Premier League football. Polymarket is the only venue for
the foreseeable future; Kalshi is deferred and appears only under
"Deferred" at the end. The order of work is
backtest scoring first, then paper trading, then live execution. Live execution
is planned here but is not to be written until its security design is agreed.

## Reference implementation

[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (MIT) was read as a
reference. It is an LLM agent that writes and backtests strategy code over
continuous OHLCV price series for equities, crypto and futures. It has no
binary-contract backtester, no probability scoring, and its "shadow account" is a trade-journal counterfactual rather than paper trading. Its
system prompt forbids the LLM from producing numbers, so it contains no
LLM-as-forecaster. What it does offer, and what this plan reuses, is:

- `agent/src/tools/prediction_market_tool.py`: a read-only Polymarket Gamma and
  CLOB client with a careful resolution-evidence ladder (CLOB `tokens[].winner`
  before Gamma `umaResolutionStatus`), which is the logic needed to label settled
  outcomes for scoring. To be ported with its MIT notice.
- `agent/backtest/loaders/_http.py`: per-host throttled JSON GET.
- `agent/backtest/validation.py` and `agent/backtest/metrics.py`: pure
  numpy/pandas bankroll statistics (Sharpe, drawdown, bootstrap confidence
  intervals, Monte Carlo trade-order permutation, walk-forward consistency).
- Design patterns, not code: run-directory artifact layout; the hypothesis
  registry as a template for a forecast registry; the hash-chained append-only
  audit ledger; the filesystem kill switch; the mandate model of hard caps and
  the fail-closed order guard.

Everything else (its engines, agent loop, broker connectors, frontend) is either
bound to continuous-price instruments or irrelevant, and is not reused.

## Mathematical core

Each market is a contract paying 1 if a binary event occurs and 0 otherwise. A
forecaster emits a probability $\hat p \in (0,1)$ at information-cutoff time $t$,
using only information available before $t$. Forecasts are scored against the
realised outcome $y \in \{0,1\}$ with strictly proper scoring rules, so that
reporting one's true belief is the unique optimum:

$$\text{Brier} = (\hat p - y)^2, \qquad
\text{Log score} = -\bigl[y \ln \hat p + (1-y)\ln(1-\hat p)\bigr].$$

The market price $q$ at time $t$ is itself a forecast and is the baseline; a
forecaster has skill only if its mean score beats the market's. Edge is the
expected value of a unit position after fees, and position size follows the
Kelly criterion for a binary contract bought at price $q$,

$$f^{*} = \frac{\hat p - q}{1 - q},$$

typically scaled down by a fixed fraction. Full derivations, the fee models for
each venue, and the calibration decomposition are to live in `docs/` and are
tasks below, not repeated here.

## Phase 6: Restructure and archive
1.  [completed] Archive the original project without deleting it.
    - Move `src/`, `tests/`, `plots/`, `reports/`, `data/`, `docs/`,
      `CURRENT_STATE.md` and the old `README.md` to `archive/prediction_markets/`
      with `git mv` so history is preserved.
    - Add a short `archive/prediction_markets/README.md` stating what the
      archive is and that its `pm` entry point is no longer wired up.
2.  [completed] Rename the project to `vibe-predict` with package `vp`.
    - `pyproject.toml`: name, description, `vp = "vp.cli:main"` entry point,
      hatch wheel target `vp`.
    - Align tooling with the global conventions: `ruff` target matched to the
      pinned Python, `ty` configured with `error-on-warning`, pre-commit ruff
      revision updated, `detect-secrets` baseline regenerated.
3.  [completed] Port the reusable Vibe-Trading modules into `vp/` with attribution.
    - `vp/venues/polymarket.py` from `prediction_market_tool.py`, stripped of
      its `BaseTool` dependency.
    - `vp/venues/_http.py`, and `vp/backtest/bankroll.py` adapting the
      bankroll arithmetic of `metrics.py` and `validation.py` to per-bet P&L
      arrays (the two files proved bound to bar-based trading; see
      `docs/provenance.md`).
    - Record provenance and licence in `docs/provenance.md` and a `NOTICE` file.
4.  [completed] Fresh documentation skeleton.
    - New root `README.md` (ASCII tree, documentation index, overview).
    - `docs/index.md`, `docs/architecture.md`, `tests/reports/` directory.
    - Offline tests for the resolution ladder and bankroll arithmetic
      (`tests/`); the live Polymarket smoke test is blocked in the development
      container by its egress policy and is carried into task 8.

## Phase 7: Data layer
5.  [completed] Define the binary-contract record.
    - Market id, question text, outcome tokens, bid/ask/mid, order-book depth,
      volume, timestamps, lifecycle status, resolution state, and resolved
      outcome, as a typed dataclass in `vp/markets/schema.py`.
6.  [completed] Polymarket client.
    - The ported client (task 3) exposing search, market, order book, price
      history and resolution, wrapped behind the record in task 5.
7.  [completed] Domain adapters for `cs2`, `weather`, `epl`.
    - Discovery filters seeded from the archived `market_config.json` keywords
      and Polymarket tag IDs.
    - Parse each question into structured fields (teams and date; station,
      threshold and date; fixture and date) for use by forecasters.
    - Parsers are built from question strings recorded in the archived
      reports; the EPL match forms are unverified until the first live run.
8.  [in-progress] Historical dataset of resolved markets for backtesting.
    - Verify that resolved markets and their price histories are retrievable;
      the archived project found some closed-market Gamma endpoints returning
      400/404, so this is a measurement, not an assumption.
    - Persist to `data/` as Parquet with a documented schema.
    - [completed] `vp build-dataset` implemented, with the retrievability
      counts printed as its report; tested against a fake source.
    - [pending] Run it live: the development container cannot reach
      Polymarket, so the measurement itself, and the Gamma tag ids for CS2
      and weather, wait on a run from a machine with access.
9.  [completed] Snapshot collector for ongoing data.
    - Periodic capture of live prices and books for the three domains, feeding
      both future backtests and paper trading.

## Phase 8: Forecasting
10. [pending] Forecaster interface.
    - `forecast(market, cutoff) -> Forecast(p_hat, rationale, cost)` where
      `cutoff` is passed explicitly and every data access is filtered to before
      it, which is the look-ahead safeguard.
11. [pending] Baseline forecasters.
    - Market mid-price at cutoff; constant 0.5; climatology for weather.
12. [pending] LLM forecaster (the "vibe"), the central component.
    - Per-domain structured elicitation prompt with the information cutoff
      stated, returning a probability and a rationale; rationale and cost
      logged per call; optional ensemble over repeated samples.
    - Tool access for the model (pre-cutoff match results, fixtures, station
      observations) so that, as in Vibe-Trading, the model reasons over
      retrieved evidence rather than from memory alone.
    - Document the prompt design and its known failure modes in
      `docs/forecasters.md`.
13. [pending] Statistical forecasters.
    - Elo or Bradley-Terry ratings for CS2 and EPL fitted on pre-cutoff results.
    - Climatology and, where available, published numerical-weather-prediction
      output for weather thresholds.
14. [pending] Forecast registry.
    - Append-only JSONL of (market, forecaster, cutoff, $\hat p$, rationale
      hash), modelled on Vibe-Trading's hypothesis registry.

## Phase 9: Backtest scoring
15. [pending] Proper scoring and calibration.
    - Brier, log score, and skill scores relative to the market baseline;
      reliability diagram; Murphy decomposition into reliability, resolution
      and uncertainty. Derivations in `docs/scoring.md`.
16. [pending] Edge, fees and sizing.
    - The Polymarket fee model; expected value of a unit position; Kelly
      fraction and fractional Kelly. Derivations in `docs/sizing.md`.
17. [pending] Event-contract fill simulator.
    - Fills against the recorded book at cutoff, settlement to 0 or 1 at
      resolution, equity curve; bankroll statistics via the ported metrics and
      validation modules.
18. [pending] Backtest report.
    - CLI `vp backtest` producing calibration plots, cumulative score versus
      market, equity curve, and per-domain breakdown, with a test report
      recording runtime in `tests/reports/`.

## Phase 10: Paper trading
19. [pending] Forward loop.
    - Scheduled cycle of snapshot, forecast, simulated order, and ledger write;
      ledger as a hash-chained append-only JSONL.
20. [pending] Resolution tracking and forward scoring.
    - Detect settlement, book P&L, and score forward forecasts with the same
      code as the backtest.
21. [pending] Leakage check.
    - Compare forward scores with backtest scores per forecaster; a material gap
      indicates look-ahead in the backtest.

## Phase 11: Live execution (planned, not to be written yet)
22. [pending] Security design, agreed before any code.
    - Key storage in the OS keyring, never in the repository or `.env`.
    - Separate credentials for paper and live, structurally unable to cross.
    - Mandate of hard caps: max order notional, max total exposure, max trades
      per day, expiry; fail-closed order guard.
    - Filesystem kill switch independent of the running process.
    - Human approval for every write; hash-chained audit ledger.
23. [pending] Polymarket CLOB execution adapter (order signing and placement),
    blocked on task 22.
24. [pending] Canary rollout at minimal stake with the mandate enforced.

## Phase 12: Documentation and tests (continuous)
25. [pending] Each phase lands with its `docs/` page linked from `docs/index.md`
    and the README, and a test report in `tests/reports/` with runtimes.
26. [pending] Pre-commit hooks (`ruff`, `ty`, `detect-secrets`) passing on every
    commit.

## Deferred
- Kalshi as a second venue. Not in scope for the foreseeable future. The archived
  `src/collectors/kalshi.py` and the `KXCSGOGAME` and `KXENGLISHPREMIERLEAGUE`
  series tickers are the starting point if this is revisited.
