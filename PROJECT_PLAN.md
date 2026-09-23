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
`vibe-predict`, import package `vp`, CLI command `vp`): a platform on which
people build, score and run forecasting strategies for binary
prediction-market contracts on Polymarket through conversation with an LLM.
Phases 6 to 12 built the engine on three domains, CS2 esports, weather and
English Premier League football; the domains open up from Phase 17 and
nothing written from Phase 13 on may enumerate the three. Polymarket is the
only venue for the foreseeable future; Kalshi is deferred and appears only
under "Deferred" at the end. The order of work was backtest scoring first,
then paper trading, then the hosted platform; live execution is planned and
gated on an agreed security design (Phases 11 and 21). Phases 13 to 23 were
rewritten on 2026-09-18 after the full review of the reference
implementation and the direction that the product must serve many users.

## Reference implementation

[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (MIT) was read
twice: on 2026-09-13 (version 0.1.15, commit `afe7d7d`) for code worth
porting, recorded in `docs/provenance.md`, and in full on 2026-09-18 (commit
`e5f7195`) for the product, its collaborative tools and its scaling posture,
recorded in `docs/vibe_trading.md`. It is an LLM research workspace that
writes and backtests strategy code over continuous price series for
equities, crypto, futures, forex and options, with a factor zoo, committee-
style agent teams, a broker-journal counterfactual, eighteen broker
connectors behind a bounded mandate, sixteen chat-channel adapters, a
scheduler, an MCP server and a web UI. It has no binary-contract backtester,
no probability scoring and no forecaster (its model is forbidden to produce
numbers), and it is built for one operator on one machine.

What this plan reuses from it:

- Three ported modules, attributed in `NOTICE` and `docs/provenance.md`: the
  read-only Polymarket client with its resolution-evidence ladder, the
  throttled HTTP helper, and the bankroll arithmetic rewritten over per-bet
  P&L.
- Design patterns, re-derived for binary contracts under an explicit cutoff
  and never copied: the run-directory artifact trail and run cards; the run
  manifest that hashes methodology and excludes timestamps; the hypothesis
  registry and the research-goal ledger of criteria and evidence; the
  hash-chained audit ledger; the filesystem kill switch; the mandate of hard
  caps with a fail-closed order guard and a consent path no tool can reach;
  the factor zoo's purity and lookahead gates and one-line bench; swarm
  presets as committee DAGs; editable skills with progressive disclosure;
  persistent memory; the grounding gate on numbers; the loop guards; the
  propose-then-commit rule for anything an agent schedules; chat channels
  with pairing codes and operators; scheduled research with playbooks and
  delivery targets; an MCP server that never carries an order tool; the
  offline evals harness; the contributor checklist and CI gates; a
  reproducible research lab. `docs/vibe_trading.md` § 7 maps each to its
  phase.

What it does not reuse: executing generated code, the engines, loaders and
brokers for continuous instruments, its prompts, skills, presets, playbooks,
text, name, marks and assets (`docs/vibe_trading.md` § 8 and § 9).

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

typically scaled down by a fixed fraction. Full derivations, the fee model, and
the calibration decomposition live in `docs/scoring.md` and `docs/sizing.md`.

Three further rules govern every claim the platform makes from Phase 13 on:

- **Fees.** The venue charges takers, never makers, $C \cdot r \cdot p(1-p)$
  on $C$ shares matched at price $p$, with $r$ set per market category and
  published per market (in 2026: sports 0.05, weather 0.05, crypto 0.07,
  politics 0.04, geopolitics 0). The rate is read from the market, never
  assumed, and enters sizing through the effective price.
- **Power.** For the paired difference $d_i = \text{Brier}_f(i) - \text{Brier}_q(i)$
  between a forecaster and the market on the same markets, with standard
  deviation $\sigma_d$, detecting a mean edge $\delta$ at two-sided 5% with
  80% power needs $n \approx (z_{0.975} + z_{0.8})^2 \sigma_d^2 / \delta^2 = 7.85\,\sigma_d^2/\delta^2$
  settled markets. With $\sigma_d$ near 0.13, as an on-chain Polymarket
  benchmark's power analysis implies (Foresight Arena, 2026: about 350
  markets for a 0.02 edge), a two-point edge needs about 350 settled markets
  and a one-point edge four times that. Every run card states $n$, $\sigma_d$
  measured on the run, and the $n$ its claimed edge would need; nothing is
  ranked below a minimum count.
- **The evidence window.** A language model may know the outcome of any
  market that resolved before its training cutoff, and asking it to pretend
  otherwise does not work: the 2026 forecasting literature measures a Brier
  gap of about half between "simulated ignorance" and true ignorance. An LLM
  forecaster's backtest therefore counts as evidence of skill only on markets
  that resolved after the documented training cutoff of every model it uses;
  earlier markets are reported separately as contaminated. The forward
  ledger, where nothing after the cutoff exists, is the evidence that counts
  most, and the leakage check of Phase 10 is the measurement.

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
8.  [completed] Historical dataset of resolved markets for backtesting.
    - Verify that resolved markets and their price histories are retrievable;
      the archived project found some closed-market Gamma endpoints returning
      400/404, so this is a measurement, not an assumption.
    - Persist to `data/` as Parquet with a documented schema.
    - `vp build-dataset` implemented, with the retrievability counts printed
      as its report; tested against a fake source.
    - Measured live on 2026-09-13 (`tests/reports/phase7_data_layer.md`):
      resolved markets are served with a settlement label for 97% (EPL,
      12,716), 89% (CS2, 88,668) and 99.8% (weather, 134,077) of the closed
      markets discovered; price histories are served for every sampled
      market, at hourly bars for markets closed within about the last month
      and daily bars before that. Gamma tag ids recorded for all three
      domains; the catalogue's 100-row and 2000-offset caps handled by an
      end-date walk; the parsers corrected to the live question forms.
9.  [completed] Snapshot collector for ongoing data.
    - Periodic capture of live prices and books for the three domains, feeding
      both future backtests and paper trading.

## Phase 8: Forecasting
10. [completed] Forecaster interface.
    - `forecast(market, cutoff) -> Forecast(p_hat, rationale, cost)` where
      `cutoff` is passed explicitly and every data access is filtered to before
      it, which is the look-ahead safeguard.
11. [completed] Baseline forecasters.
    - Market mid-price at cutoff; constant 0.5; climatology for weather.
12. [completed] LLM forecaster (the "vibe"), the central component.
    - Implemented and tested offline against a fake client; not yet run
      against the API, which needs credentials the development container
      does not hold (see the Phase 8 report).
    - Per-domain structured elicitation prompt with the information cutoff
      stated, returning a probability and a rationale; rationale and cost
      logged per call; optional ensemble over repeated samples.
    - Tool access for the model (pre-cutoff match results, fixtures, station
      observations) so that, as in Vibe-Trading, the model reasons over
      retrieved evidence rather than from memory alone.
    - Document the prompt design and its known failure modes in
      `docs/forecasters.md`.
13. [completed] Statistical forecasters.
    - Elo for CS2 and EPL fitted on pre-cutoff resolutions from the dataset
      itself. Climatology from realised buckets in the dataset; Open-Meteo's
      archive and previous-runs endpoints were rate-limited from the
      development container and are left as a documented extension.
    - Elo or Bradley-Terry ratings for CS2 and EPL fitted on pre-cutoff results.
    - Climatology and, where available, published numerical-weather-prediction
      output for weather thresholds.
14. [completed] Forecast registry.
    - Append-only JSONL of (market, forecaster, cutoff, $\hat p$, rationale
      hash), modelled on Vibe-Trading's hypothesis registry.

## Phase 9: Backtest scoring
15. [completed] Proper scoring and calibration.
    - Brier, log score, and skill scores relative to the market baseline;
      reliability diagram; Murphy decomposition into reliability, resolution
      and uncertainty. Derivations in `docs/scoring.md`.
16. [completed] Edge, fees and sizing.
    - The Polymarket fee model; expected value of a unit position; Kelly
      fraction and fractional Kelly. Derivations in `docs/sizing.md`.
17. [completed] Event-contract fill simulator.
    - Fills against the recorded book at cutoff, settlement to 0 or 1 at
      resolution, equity curve; bankroll statistics via the ported metrics and
      validation modules.
18. [completed] Backtest report.
    - CLI `vp backtest` producing calibration plots, cumulative score versus
      market, equity curve, and per-domain breakdown, with a test report
      recording runtime in `tests/reports/`.

## Phase 10: Paper trading
19. [completed] Forward loop.
    - Scheduled cycle of snapshot, forecast, simulated order, and ledger write;
      ledger as a hash-chained append-only JSONL.
20. [completed] Resolution tracking and forward scoring.
    - Detect settlement, book P&L, and score forward forecasts with the same
      code as the backtest.
21. [completed] Leakage check.
    - Compare forward scores with backtest scores per forecaster; a material gap
      indicates look-ahead in the backtest.

## Phase 11: Live execution (superseded by Phase 22 on 2026-09-19)
The operator-machine path this phase planned is not built: the owner
decided live execution is hosted only, so that strategies trade while the
user's computer is closed. The safety layer stays and is reused; the
design page becomes the base for version 2.
22. [superseded] Security design, agreed before any code.
    - Proposed in `docs/security.md` (2026-09-13); awaiting agreement.
    - The safety layer it specifies (mandate guard, kill switch,
      environment separation, approvals, keyring access) is implemented
      and tested in `vp/live/` so the design can be judged with code in
      hand; it cannot sign or send an order.
    - Key storage in the OS keyring, never in the repository or `.env`.
    - Separate credentials for paper and live, structurally unable to cross.
    - Mandate of hard caps: max order notional, max total exposure, max trades
      per day, expiry; fail-closed order guard.
    - Filesystem kill switch independent of the running process.
    - Human approval for every write; hash-chained audit ledger.
23. [superseded] Polymarket CLOB execution adapter (order signing and placement),
    blocked on task 22; replaced by Phase 22, task 113.
24. [superseded] Canary rollout at minimal stake with the mandate enforced;
    replaced by Phase 22, task 115.

## Phase 12: Documentation and tests (continuous)
25. [completed] Each phase lands with its `docs/` page linked from `docs/index.md`
    and the README, and a test report in `tests/reports/` with runtimes.
26. [completed] Pre-commit hooks (`ruff`, `ty`, `detect-secrets`) passing on every
    commit.
27. [completed] Browser dashboard (`vp ui`): a read-only local page over the
    data root, standard library only, with datasets, backtest runs and
    figures, the paper ledger and the latest snapshots (`docs/ui.md`).

## Phases 13 to 23: the hosted platform

Revised on 2026-09-18 after the full review of Vibe-Trading
(`docs/vibe_trading.md`) and the direction that the product must serve many
users (`docs/scaling.md`). Phases 13 to 15 keep the meaning they had in the
2026-09-18 product design (`docs/product.md`); hosted live execution, which
was Phase 16, is now Phase 22, the last phase built, because the phases
between produce the evidence for whether any strategy should trade real
money and the machinery (portfolio risk, strategy health, promotion
criteria, a platform proven under load) that makes doing so at scale
defensible. Decided on 2026-09-19: live execution is hosted only, so a
strategy trades while the user's computer is closed; no operator-machine
path is built. Every phase below is pending; the order is the order of
work, except where the build order below says otherwise, and each phase
begins only after the user has agreed to it.

**Build order, decided 2026-09-23: the interface first.** The owner asked
for the browser interface as early as possible. It depends on less than
the task numbering suggests: the web service and sign-in, and nothing
else, because the market cards, P&L charts and paper views can read the
snapshot files and the hash-chained ledger the engine already writes. So
the work runs in this order, with the task numbers unchanged:

1. **The app in a browser:** 28 (web service), 29 (sign-in, sessions and
   tokens), 37 (the existing views on the service, and fees in paper
   trading).
2. **The friendly interface, pulled forward from Phase 14:** 39 to 47,
   built on what the engine already writes. The owner's request is the
   go-ahead for these tasks to start ahead of the rest of Phase 13.
3. **The rest of Phase 13 behind it:** 30 to 33, 35 and 36 (the remaining
   storage, jobs, the market-data service, the evidence collectors,
   budgets, observability). The interface moves onto each as it lands:
   market cards from snapshot files to the market-data service, a backtest
   started from the page from a direct call to a job with progress.
4. **At the end of the build:** the cloud deploy of task 34 (flag F16), then
   48 and 49, which need a public host and real people, and the
   host-dependent measurements of task 38.

Phase 15 onward keeps its order. Everything runs on the development
machine until step 4.

Principles that hold for everything below:

1. **One engine, many surfaces.** `vp/` is called by the CLI, the web
   service, the job workers, the MCP server and the channel bots, and knows
   about none of them. Per-user work runs the same functions on per-workspace
   state.
2. **Strategies are data, not code.** A strategy is a versioned spec the
   engine interprets. No user-authored or model-authored code is executed
   anywhere. This is what makes multi-tenant execution safe, runs
   reproducible, and previews honest.
3. **The model's only number is a probability.** Every other figure a user
   sees (a score, a P&L, a count, a cost) is computed by the engine from data
   and rendered from data. A probability is scored with a strictly proper
   scoring rule, so the one number the model produces is the one number that
   can be held to account.
4. **Shared work is computed once; private work is metered.** Market data,
   evidence, platform forecasts and benches are public goods memoised by
   content hash; strategies, accounts, sessions and budgets are private.
5. **The cutoff discipline extends to evidence.** A backtest may read only
   what the evidence archive captured before the cutoff or what a source
   serves with true point-in-time semantics. Nothing is fetched live inside a
   backtest. Live retrieval belongs to the forward loop, at the present.
6. **A claim of skill needs power.** Every run card states the number of
   settled markets it rests on and the number a claimed edge would need
   (Mathematical core); an LLM forecaster's backtest counts as evidence only
   on markets that resolved after the model's documented training cutoff,
   and the forward ledger is the evidence that counts most.
7. **Every phase lands whole**: a design page in `docs/` agreed before code,
   tests that run offline, a report in `tests/reports/` with what was
   measured live, status tags updated here, and the decisions it needs listed
   before it starts.

## Phase 13: Platform foundation for many users
Design: `docs/product.md` (architecture, accounts and money) and
`docs/scaling.md` (tenancy, storage, queue, market-data service, budgets,
capacity). The browser becomes the whole product for the user; the command
line stays for developers and the operator. Built for many users from the
first release, on one host at first (`docs/scaling.md` § 12, stage A).
Started 2026-09-21; what is built is recorded in `docs/platform.md`.

28. [in-progress] Web service over the unchanged engine.
    - Landed: the configuration module, sole reader of the environment,
      with no default for any secret, redaction of the database URL, and
      `tests/test_config_gate.py` proving no second reader exists.
    - Landed 2026-09-23: the FastAPI application (`vp serve`), health and
      readiness, the OpenAPI page, JSON errors, security headers, the
      access-log filter that keeps sign-in tokens out of logs, and the
      dashboard's read endpoints behind sign-in; `vp db migrate`. The
      service refuses to start as any role row-level security does not
      bind. Verified by driving Chromium through the whole flow, which
      found two faults the request tests could not (`docs/platform.md`).
    - Outstanding: the endpoints mirroring the CLI's write commands
      (build, snapshot, backtest, paper run, settle, leakage), which
      arrive as jobs with task 31.
    - FastAPI application with a request principal on every route, health
      and readiness endpoints, the OpenAPI page as the technical user's API
      reference, JSON errors, structured logs through the redaction filter.
    - One configuration module that is the only reader of the environment
      (a lint rule enforces it); typed settings; no secret has a default.
    - Endpoints mirroring the CLI (build, snapshot, backtest, paper run,
      settle, leakage) and the dashboard's read endpoints moved unchanged.
29. [in-progress] Identity, workspaces and tenancy.
    - Landed: the `Principal` with derived attribution, roles held within
      a workspace and an operator role that reaches no workspace data; the
      workspaces, users and memberships tables with row-level security;
      `tenant_session`; and the tenancy suite, which proves a query that
      forgets its filter returns nothing, that naming another workspace
      explicitly returns nothing, and that a context cannot outlive its
      transaction.
    - Landed 2026-09-23: email magic-link sign-in with a confirm page (so
      mail scanners cannot spend the link), sessions, API tokens with read
      and write scopes, cross-site request checks, and a personal
      workspace on first sign-in. Migration 0002 crosses the tenancy
      boundary only through five narrow `SECURITY DEFINER` functions, so
      the web process never holds the owner's credentials.
    - Outstanding: OpenID Connect (prepared for, not needed yet); a
      per-address-and-IP request limit with task 36; the expiry sweep with
      task 31.
    - `Principal` with `subject`, `auth_method`, `attributable` (derived,
      never caller-set), `workspace`, `roles`; email magic-link sign-in;
      OpenID Connect prepared but not shipped; HTTP-only session cookies;
      cross-site request checks; single-use tickets for event streams.
    - Personal workspace per user; team workspaces use the same tables;
      roles owner, editor, viewer, operator. Every per-user table carries
      `workspace_id` and is protected by Postgres row-level security set from
      the principal.
    - API tokens hashed at rest, scoped and revocable.
    - A tenancy test suite that attempts every cross-workspace read and
      write and expects nothing.
30. [in-progress] Storage.
    - Landed: the migration runner (one transaction per file, checksummed,
      immutable once applied) and `0001_foundation.sql`.
    - Outstanding: the remaining tables, object storage, the DuckDB read
      path, partitioning and archival.
    - Postgres schema: users, workspaces, memberships, strategies,
      strategy versions, runs and manifests, forecasts with memo keys, paper
      accounts, ledger entries, jobs, budgets and spend, settings, tokens,
      channels, audit. Versioned migrations run as a job.
    - Ledger entries per account with the hash chain of `vp/paper/ledger.py`
      preserved: an append takes an advisory lock on the account, so
      `Ledger.verify` runs unchanged over an export and a user can verify
      their own ledger offline.
    - Object storage for dataset versions, histories, snapshots, artifacts
      and archives; a DuckDB read path over it; a local disk cache.
    - Monthly partitions for ledger entries and forecasts; archive-to-Parquet
      with chain hashes after the retention window.
31. [pending] Jobs and schedules.
    - A `jobs` table claimed with `SKIP LOCKED`: kind, idempotency key,
      priority, run-after, attempts, lease and heartbeat, progress, result,
      workspace, budget reservation; dead-letter state; cancellation.
    - Worker pools per kind (ingest, evidence, dataset, forecast-LLM,
      forecast-stat, backtest, paper cycle, settlement, delivery, admin),
      sized independently; one image, three entry points (web, worker,
      ingest).
    - Cron schedules with IANA timezones for snapshots, cycles, settlements
      and refreshes; the scheduler is a job that enqueues jobs.
    - `vp jobs` for the operator: list, inspect, retry, drain.
32. [pending] Market-data service: one subscription for everyone.
    - The CLOB market WebSocket for every tracked token with dynamic
      subscribe and unsubscribe, the custom `best_bid_ask`, `new_market` and
      `market_resolved` events, and the ten-second `PING`; in-memory books;
      quotes coalesced to one row per market per minute and on every
      top-of-book change for held markets.
    - Discovery by Gamma keyset pagination (`after_cursor`, April 2026),
      replacing the end-date walk in `vp/markets/polymarket.py`.
    - Resolutions from the `market_resolved` event, the Data API v2
      `/v2/resolutions` endpoint and the CLOB `winner` flag, with an hourly
      reconciliation sweep; closed is still not resolved.
    - Price history moved to the Data API v2 host where the CLOB endpoint
      is retired; the client's endpoint table re-verified against live
      responses and the data-layer page updated.
    - The existing snapshot writer runs from the in-memory state on the
      schedule, so every downstream file is unchanged.
    - A token bucket per venue host, set from measured limits and recorded
      in the report; fan-out to consumers by `LISTEN`/`NOTIFY`.
    - Freshness objectives: newest quote under 60 s at the 99th percentile;
      resolution to label under 15 min; both measured and alerted.
33. [pending] The evidence archive starts capturing now.
    - The collectors of Phase 17 that capture what cannot be recovered later
      (Open-Meteo forecast runs for every city in the weather markets,
      fixtures and results, CS2 schedules, daily headline sets per domain)
      are scheduled in this phase, because time-indexed evidence only
      accumulates forward and every week not captured is a week no backtest
      can use honestly. Storage in object storage as Parquet with capture
      times; the readers come in Phase 17.
34. [pending] Deploy. **Cloud deployment deferred to the end** (decided
    2026-09-23, flag F16): the platform is built and verified on a local
    stand-in, and the Fly.io account, the region probe of F1 and the
    public deploy come when the build is otherwise done, and in any case
    before anything reaches a real user.
    - Now: the same container image run locally with Docker Compose,
      Postgres 16 and an S3-compatible object store (MinIO), so every code
      path the cloud will run is exercised here; migrations as a job; the
      GitHub Actions workflow that runs the tests and builds the image,
      without the deploy step.
    - Deferred: one container image; managed Postgres with point-in-time recovery;
      object storage; a staging environment that receives every deploy
      first; GitHub Actions runs the tests, builds the image, runs
      migrations as a job and deploys `master`; HTTPS and a domain; secrets
      in the host's secret store; a restore drill with its time recorded.
    - `vp admin`: data refresh, budgets, costs, pause a workspace, platform
      halt; an admin page only if these turn out to be needed often.
35. [pending] Budgets and LLM operations.
    - Platform key server-side; per-workspace monthly budget (proposed
      default $5, operator-adjustable); the estimated cost of a run shown
      before it starts, reserved, and debited on completion from measured
      usage; an optional own key under envelope encryption in the
      key-management service.
    - Prompt caching of the stable prefix; the provider's batch endpoint for
      backtests at half price when the user accepts the delay; one
      concurrency limiter per provider key across all workers; backoff on
      rate-limit responses; queue priority for interactive work.
    - Spend attributed per forecast (model, tokens, cache hits, dollars) and
      shown by workspace, forecaster and domain.
36. [pending] Observability and the platform halt.
    - OpenTelemetry traces across request, job and venue call; metrics for
      queue depth and age, job latency, LLM spend and cache hit rate,
      WebSocket lag, quote freshness, resolution delay, ledger append
      latency, error rates; dashboards; alerts with a runbook each.
    - The platform halt as a row: while set, no worker runs a job, no LLM
      call is made and no order is prepared; a workspace halt likewise; each
      is a ledger entry with its principal.
37. [in-progress] The existing views on the new service, and fees in paper
    trading.
    - Landed 2026-09-23 (F5): the client reads each market's `feesEnabled`
      and `feeSchedule` (rate and exponent) into the record and the
      snapshot files; `FeeModel` takes the exponent; a paper order is
      sized at the market's own rate through the same `FeeModel` the
      backtest uses and records `fee`, `fee_rate` and `fee_source`
      (`market`, or `assumed` when the venue states none); settlement is
      net of it because the stake already includes it. Live on that day
      every CS2, weather and EPL market stated rate 0.05, exponent 1.
    - Outstanding: the views from tenant-scoped queries, and the backtest
      reading per-market rates (task 77; older datasets lack the columns
      and read as "not stated").
    - Overview, backtests, paper and markets rendered from tenant-scoped
      queries instead of a data root; the same page, fonts, charts and
      glossary; a browser end-to-end test with the preinstalled Chromium.
    - Paper cycles charge the taker fee from each market's `feeSchedule`
      through the same fee function the backtest uses, record it per order
      and settle net of it (F5); the paper-trading page and the glossary
      say so.
38. [pending] Phase 13 report.
    - Measured: request latency, ingestion lag and reconnects, venue rate
      limits observed, job start latency, cost per user-day on the staging
      load, restore time. The capacity model's stage-A column replaced by
      numbers.

Done when (on the local stand-in until the deferred deploy of task 34)
one person can sign in, see the dashboard's four views over live
data the service ingests itself, run a backtest and a paper cycle from the
page, watch them progress, and see what it cost; when a second person cannot
see any of it; and when the report holds the measurements above.

Decisions before starting: hosting provider and region; who operates
budgets and abuse; the object-storage provider; whether to prepare for the
venue's builder programme (attributed volume) now or in Phase 22.

## Phase 14: Friendly for everyone
Design: `docs/product.md` (the experience). Two people equally at home: one
who has never seen a prediction market and one who wants the bootstrap
interval. One backend, two reading levels.

39. [pending] Simple and Detailed reading levels: one switch, remembered,
    every screen rendered both ways; Simple never omits a fact that would
    change a decision, it changes the words and the density.
40. [pending] Guided first run: what this is, pick interests, see your
    markets, watch a sample strategy run in paper. Three to five screens, a
    button each, skippable, resumable.
41. [pending] Brokerage-style home: play-money balance, its chart, what
    changed today, one next step; Detailed adds per-strategy P&L, exposure,
    skill and settled counts.
42. [pending] Market cards, from the snapshot files first and from the
    market-data service once it lands (build order, step 3): the question in
    plain words, "62% chance", closes in two days, and in Detailed the
    quotes, depth, parsed fields, forecasts and history.
43. [pending] A P&L chart wherever money is shown, with the market-following
    baseline drawn alongside so "better than doing nothing" is visible
    without a number; every number has a sentence in Simple mode and a
    dotted glossary term in Detailed.
44. [pending] Fees shown in both modes. The 2026-09-13 assumption that sport
    and weather markets carry no fee is withdrawn: the venue's 2026 schedule
    charges takers on sports (0.05), weather (0.05), crypto (0.07) and most
    other categories, at $C \cdot r \cdot p(1-p)$; the fee is read from each
    market's `feeSchedule`, never assumed, and Simple mode says what it
    costs in cents.
45. [pending] Learn: prediction markets, why the price is a forecast, what a
    backtest is and is not, paper trading, and why beating the market is
    hard, citing the 2026 evidence that frontier models trail
    superforecasters by about 0.02 Brier and that the market price is a
    strong forecast (Mathematical core, references).
46. [pending] Settings: interests, play money, reading level, theme,
    notifications; in Detailed the model tier, budget, own key, data
    refresh, export of every record the workspace holds.
47. [pending] Internationalisation structure (message catalogues, locale
    switch, number and date formatting) with English shipped; accessibility
    to WCAG 2.2 AA (keyboard, contrast, screen-reader labels on charts).
48. [pending] Terms of use, age gate, jurisdiction notice, privacy notice
    (export and delete per workspace), and the first-screen statement that
    this is a tool for building and testing strategies, not advice.
49. [pending] Usability sessions with at least three people who have never
    used a prediction market, the fixes they produce, and the Phase 14
    report (task completion, time to first strategy watched, words that
    confused).

## Phase 15: Research sessions and strategies from conversation
Design: `docs/strategies.md`, written and agreed before any code; it fixes
the spec, the sizing defaults, what a prompt may override, and the number
gate. This is the "vibe": the conversation that turns an idea into something
that runs, is scored, and is shown honestly.

50. [pending] Strategy spec, version 1 (data, not code).
    - **Selector**: domains, market kinds, parsed-field filters (team,
      league, city, bucket width, series format), time-to-close window,
      liquidity and spread floors, tags, exclusions.
    - **Belief**: which forecaster produces $\hat p$ (a baseline, a signal,
      a blend, a committee, or a user prompt to the LLM forecaster with the
      domain pack), and whether the market price is shown to it (default:
      no, as in Phase 8).
    - **Rule**: trade when edge after fees exceeds a threshold, on which
      side, only if the price lies in a band; optional "follow the market"
      rules with no belief at all (for example the favourite-longshot fade
      the Phase 9 report found), labelled as such.
    - **Sizing**: fractional Kelly with defaults (fraction 0.25, cap 5% of
      bankroll, absolute stake cap, maximum open positions, maximum exposure
      per event), a whitelist of fields a prompt may override, and hard caps
      a prompt may not.
    - **Schedule**: cutoffs as hours before close and cycle cadence.
    - JSON schema; immutable versions; a deterministic plain-language
      rendering (not by the model) so that what the user confirms is exactly
      what runs; a diff between versions.
51. [pending] Prop markets the spec needs: over/under totals, handicaps,
    halftime, exact score, odd/even, anytime scorer, per-map, with each
    market's resolution description stored and shown.
52. [pending] Compiler: prompt to spec through structured output, with
    clarifying questions when a field is ambiguous, a refusal when a request
    needs a field the spec lacks (a constraint is never silently dropped),
    and the rendered restatement the user confirms.
53. [pending] Preview before anything runs: the markets the selector picks
    now, historical counts per month, example questions, the estimated cost
    of a backtest and of a month of paper trading, and the sample size the
    selector could ever provide against the sample size an edge would need.
54. [pending] Research session agent.
    - Tools: search markets, explain a market, evidence at a cutoff, preview
      a selector, run or fetch a backtest, paper status, compare runs, read
      the signal bench, read Learn and the glossary. No tool fetches the web
      inside a backtest; live retrieval exists only for the present.
    - The number gate: the assistant's text may carry no figure that is not
      in a tool result; figures are rendered from data by the page, and a
      draft that fails is regenerated once and then released with the
      failing figures replaced by a reference to the data.
    - Loop guards: a no-progress detector (eight tool calls without a new
      observation stop the turn with a visible request), an identical failing
      call refused from its second failure, per-session token, turn and time
      budgets, cancellation, cost shown live.
    - Streaming progress for long runs through the job system.
55. [pending] Per-user memory: interests, risk appetite, sizing preferences,
    past decisions, visible and editable and deletable by the user, injected
    into prompts as context, never used to change a spec without the user
    confirming the rendered spec.
56. [pending] Domain packs: one markdown file with frontmatter per domain
    (how questions are phrased, which fields parse, which evidence exists
    and its cutoff semantics, base rates, known pitfalls), loaded with
    progressive disclosure; platform copies versioned and hashed; workspace
    copies editable; written from primary sources.
57. [pending] Run manifests and run cards.
    - Every backtest, paper period and forecast batch writes a manifest:
      spec version hash, forecaster configurations, domain pack hashes,
      dataset version, evidence archive version, fee schedule version, model
      identifiers, package versions; timestamps excluded from the hash;
      `diff` between two manifests names what changed.
    - The run card: settled count, mean scores, skill against the market
      with a paired bootstrap interval, calibration summary, P&L against the
      market-following baseline, fees paid, cost, leakage status, the sample
      size an edge of this size would need, the manifest hash, and caveats
      written from data (small $n$, daily-bar cutoffs, contaminated window).
58. [pending] Strategy lifecycle: draft, previewed, backtested, paper,
    retired (live is added in Phase 22); versions are never edited; each
    strategy has its own P&L, skill and settled-count views and its own
    paper account; refinement by conversation produces a new version.
59. [pending] Evals harness, offline and deterministic, over persisted
    session and run artifacts: every evidence call respected the cutoff; the
    confirmed spec equals the executed spec; cost was reported; the number
    gate held; `NOT_EVALUABLE` is distinct from pass; cases as JSON with the
    prompt unchanged; run in CI against a fake model.
60. [pending] First runs of the LLM forecaster against the API, on a keyed
    machine: cost per forecast per model tier, skill against the market on
    a 400-market sample per domain, split by the evidence window
    (Mathematical core): markets resolved after the model's training cutoff
    against markets resolved before it, reported separately.
61. [pending] Refinement by conversation ("smaller stakes", "only weekends",
    "ignore matches with a roster change") producing a new version with a
    diff, never editing the old.
62. [pending] Phase 15 report: compiler accuracy on a held-out prompt set,
    preview counts against realised counts, harness pass rates, the first
    LLM skill numbers with their intervals and window split.

Done when a person who has never seen a prediction market can describe a
strategy in a sentence, read back what will run, see what it would have
done and what it costs, run it in paper, and watch it, with every number
traceable to the engine.

Decisions before starting: the sizing defaults above; which spec fields a
prompt may override; the default model tiers; whether the market price is
ever shown to the LLM forecaster (proposed: only as an explicit belief
option, never by default).

## Phase 16: Signal library, forecast committees and the benchmark
Design: `docs/signals.md`. The analogue of a factor zoo for binary
contracts: tested, cutoff-safe signals with one-line benches; committees of
role forecasters; and a public benchmark that commits forecasts before the
cutoff. This phase is where "does anything beat the market" gets its
systematic answer, and where the Research Lab (Phase 23) gets its material.

63. [pending] Signal contract and gates.
    - `Signal.compute(market, evidence) -> float | None` with metadata: id,
      domains, kinds, evidence accessors required, cutoff semantics, warm-up
      (results or days needed), references, licence note.
    - A purity gate (an AST scan allowing only the evidence accessors, numpy
      and the standard mathematics; no network, files, clocks, environment,
      `eval` or `exec`) and a cutoff gate (a sentinel test that injects
      post-cutoff rows into fixtures and requires the output unchanged, and
      a test that moving the cutoff later never changes an earlier value).
    - A registry with lazy loading and a manifest export.
64. [pending] The initial library, written from the literature with
    citations, each with its bench result before it is listed.
    - Match sports: Elo with margin and map-specific ratings for CS2;
      Glicko-2; pi-ratings; Bradley-Terry with home advantage; Poisson and
      Dixon-Coles scoreline models for football, which also price over/under,
      exact score and halftime props; rest days and schedule congestion;
      roster-change flags where the archive has them.
    - Weather: climatology by window; persistence; numerical-weather-
      prediction ensemble probability of the bucket as of the last run before
      the cutoff (Phase 17 archive); bucket-sum consistency across a
      negative-risk event.
    - Market microstructure: time to close, spread and depth imbalance,
      price drift and momentum within the market, volume, the favourite-
      longshot correction, cross-market consistency (winner against maps,
      season against matches), holders concentration from the public
      analytics endpoints.
    - Calibration layers (Platt and isotonic) fitted only on pre-cutoff
      settled markets with rolling refits, so a calibrated signal is still
      cutoff-safe.
65. [pending] `vp signals bench --domain <d> --window <from>..<to>`: paired
    skill against the market on the same markets with a bootstrap interval,
    calibration, classification as alive (interval above zero), at par, or
    anti (below zero), the power statement, and rolling windows to show
    decay; results stored as data and rendered on a Signals page; one
    command reproduces any published number.
66. [pending] Blends: logistic and stacked blends of signals with the market
    price, fitted walk-forward on pre-cutoff windows, reported out of sample
    only; the honest statistical route to beating the market, and the
    strongest baseline a committee must beat.
67. [pending] Forecast committees.
    - Role forecasters (base-rate analyst, evidence analyst, market analyst,
      red team, aggregator) as a DAG behind the `Forecaster` interface;
      presets in YAML, platform copies versioned, workspace copies editable;
      each worker sees only the evidence object and the domain pack.
    - Aggregation rules as data: mean of log-odds, trimmed mean, extremising
      with a factor fitted on pre-cutoff windows, prediction capping.
    - Streamed progress, per-worker cost, the transcript stored with the
      forecast's rationale hash.
    - Evaluated against single elicitation on matched samples and against
      the best blend before any committee is offered as a default; the 2026
      literature's findings (ensembles across three to seven runs, base
      rates, similar resolved questions, capping, more retrieval) are the
      hypotheses tested, not assumptions adopted.
68. [pending] Contamination accounting: every forecaster configuration
    records the training cutoff of any model it uses; benches and run cards
    split results at that date and count only the later window as skill.
69. [pending] The public benchmark: a weekly frozen question set drawn from
    open markets across domains, forecasts committed as hashes before the
    cutoff and revealed at resolution, scored by Brier, log score and skill
    against the market with intervals, for platform configurations and
    opt-in user strategies; power-aware display (no ranking below a minimum
    settled count).
70. [pending] Signal contribution checklist for workspaces and, later, the
    community: purity gate, cutoff gate, metadata, citation, licence note,
    bench attached.
71. [pending] Phase 16 report: the bench tables per domain, which signals
    and blends are alive and over which windows, committee against single
    elicitation with cost, and the first benchmark week.

Done when the Signals page lists every signal with its live bench, when a
strategy can name a signal, a blend or a committee as its belief, and when
the benchmark has committed and scored at least one week.

## Phase 17: Evidence archive, point-in-time sources and new domains
Design: `docs/evidence.md`. Evidence is where forecasting skill comes from
and where leakage hides. The archive makes the cutoff enforceable for
sources that do not keep their own history, and the domain kit makes opening
a new domain a documented procedure rather than a rewrite.

72. [pending] Archive design: append-only captures keyed by source and
    capture time, Parquet in object storage with a manifest per capture,
    provenance and licence per source, retention rules; readers serve only
    captures with `capture_time <= cutoff`; an evidence accessor per source
    added to `Evidence` without touching any forecaster.
73. [pending] Weather: every Open-Meteo model run for every city that has
    had a market, captured at issue time with ensemble members, so the
    forecast as it stood before the cutoff is known; observations for
    labels and climatology (post-cutoff use only); the resolution source
    each market names, recorded; the rate-limit problem of 2026-09-13 solved
    by a keyed or self-hosted route decided here.
74. [pending] Football: fixtures, results, line-ups and injuries from a
    licensed or open source (candidates evaluated on licence, coverage and
    point-in-time semantics), daily; league tables derived, never fetched
    after the fact.
75. [pending] CS2: schedules, results, rosters and map vetoes from sources
    whose terms permit it (Liquipedia's API under its attribution licence;
    a paid feed optional); scrape-hostile sources are not used and the
    page says which.
76. [pending] Headlines: a daily capture of headline sets per domain from
    feeds whose terms permit it, stored with capture time, so an LLM
    forecaster in a backtest reads only what was printed before the cutoff;
    web search at forecast time is allowed only in the forward loop and is
    logged as such.
77. [pending] Fee schedules: the per-market `feeSchedule` and its history
    captured with every snapshot; the resolved datasets gain the fee rate
    in force when each market traded; the Phase 9 baselines re-run fee-aware
    and the report amended, since the zero-fee default understated the cost
    of every bet.
78. [pending] Data layer refresh against the venue's 2026 API: Data API v2
    for histories, resolutions and analytics; keyset pagination; the closed
    default on the markets endpoint; negative-risk and combinatorial fields
    recorded on the market record; the client's endpoint table re-verified
    line by line.
79. [pending] Domain onboarding kit: a new domain is membership rules, a
    parser with recorded questions, an evidence pack, signals, a domain
    pack page and tests; nothing in the platform enumerates the domains.
    Candidates ranked by data availability and market count (other
    football leagues and cups, the major North American leagues through the
    venue's sports feed, other esports titles, politics with care); the
    short-horizon crypto price markets are noted and not pursued (fee 0.07,
    a 50 ms taker delay, no evidence an LLM can add).
80. [pending] Phase 17 report: coverage and freshness per source, the
    leakage audit (forward against backtest per forecaster with the archive
    in use), and the fee-aware baseline table.

## Phase 18: Collaboration and delivery
Design: `docs/collaboration.md`. Teams, sharing, conversation about results,
and getting research to people where they already are: the collaborative
capabilities Vibe-Trading has for one operator, rebuilt for many workspaces.

81. [pending] Teams: invite by email, roles owner, editor and viewer, shared
    strategies and paper accounts, an activity feed, every change attributed
    to a principal, leaving and removal.
82. [pending] Sharing: a public read-only link to a strategy's run card,
    P&L and benchmark entry with privacy controls; fork a shared strategy
    into your workspace as a new spec with provenance; strategy cards.
83. [pending] Comments and annotations on runs, markets and strategies:
    threads, mentions, notifications, moderation by workspace owners.
84. [pending] Leaderboards, opt-in, by skill against the market with
    intervals and a minimum settled count, never by raw P&L alone; by
    domain and by window.
85. [pending] Channels: a message bus with an adapter interface; email
    first, then Telegram, Discord and Slack, and a generic webhook; pairing
    codes for unknown direct senders approved by a workspace operator;
    operator roles; a per-chat session map; in-chat commands to reset a
    session and ask read-only questions with the workspace's budget; group
    chats served by the same research session agent.
86. [pending] Scheduled briefs: playbook templates with declared variables
    and timezones ("markets closing today where my strategies disagree with
    the market by more than ten points", "settlements yesterday", "weekly
    P&L and skill"); the agent may propose a schedule and only an explicit
    confirmation on a human surface commits it; each brief ends in a
    machine-readable block a watch list renders; delivery to an opaque
    target through an outbox with retries and receipts.
87. [pending] Notifications: fills, settlements, strategy health changes,
    budget thresholds, halts; per-user preferences and quiet hours.
88. [pending] MCP server: read-only tools (search markets, market detail,
    evidence at a cutoff, forecasts, run cards, paper status, the signal
    bench) with per-user scoped tokens, over streamable HTTP; no order tool
    exists on this surface, ever.
89. [pending] Public API tokens, rate limits and outgoing webhooks for
    technical users; the OpenAPI page documents them.
90. [pending] Community contributions: the signal checklist of Phase 16
    opened to external contributors; domain pack contributions; the
    Developer Certificate of Origin decision; CI gates (no secrets, no
    market data dumps in docs, the name gate of `docs/vibe_trading.md` § 9).
91. [pending] Phase 18 report: delivery success rates per channel, brief
    latency, sharing and fork counts, moderation load.

## Phase 19: Shadow forecaster: learn from your own record
Design: `docs/shadow.md`. Vibe-Trading's Shadow Account needs a broker
export; on Polymarket every address's positions and activity are public on
the Data API, so a user can be shown their own record by pasting an address.

92. [pending] Import by public address through the Data API v2 (positions,
    activity, the cumulative P&L series), with no credentials; consent
    recorded, optional proof of ownership by a signed message, and the
    privacy notice that linking an address to an account is the user's act.
93. [pending] Diagnostics: implied beliefs from entry prices against
    outcomes (Brier, log, skill against the closing price, which is the
    closing-line value measure), calibration, favourite-longshot exposure,
    holding periods, over-trading, chasing after price moves, sizing
    consistency, fee drag, by domain and by period.
94. [pending] Rule extraction: interpretable decision lists over parsed
    fields, time to close and price bands that describe when and which side
    the user bet; the LLM proposes candidate rules in words, the engine
    fits and validates them on the record, and only validated rules become
    a spec draft.
95. [pending] Counterfactual: backtest the rule-version-of-you and compare
    the user's trades, their rules and the market-following baseline;
    attribute the gap to selection, timing and sizing.
96. [pending] Report card in Simple and Detailed, exportable; anonymised
    peer context from the public leaderboards with the sample-size caveats.
97. [pending] Phase 19 report, including whether "positions of consistently
    skilled addresses" is a signal worth adding to the library (Phase 16's
    gates apply; it is a hypothesis, not a plan).

## Phase 20: Portfolio, risk and strategy health
Design: `docs/portfolio.md`. Bets on binary contracts are correlated within
events and settle together; a paper account with thirty positions is a
portfolio whether or not the user thinks of it as one.

98. [pending] Exposure model: positions grouped by event and condition;
    dependence within an event exact (negative-risk buckets, winner against
    maps, season against matches) and between events by a documented simple
    model; worst case at settlement and loss quantiles by Monte Carlo over
    joint outcomes; concentration by event, domain and resolution date.
99. [pending] Simultaneous Kelly: the fraction vector that maximises
    expected log growth under the joint model, fractional as before,
    compared with per-bet Kelly in the backtest; per-event exposure caps as
    a constraint.
100. [pending] Risk x-ray: exposure by domain, event, date and strategy;
     "what if every favourite wins"; stake against resting liquidity; in
     Simple mode, "the most you could lose this week".
101. [pending] Strategy health: rolling forward skill against the market
     with a sequential test; states healthy, watch and decayed with explicit
     thresholds and consecutive-window rules; automatic pause in paper with
     a notification, mandatory in live; a decay report per strategy.
102. [pending] The promotion protocol: criteria with numbers for moving a
     strategy from backtest to paper to live (a minimum settled count from
     the power rule for the edge claimed, bootstrap probability of positive
     skill at or above 0.95, a forward interval that excludes zero or a
     minimum forward count with positive skill, the leakage check passed,
     health healthy for a stated number of weeks, exposure within the
     mandate); evidence rows link to runs; an audit row per criterion; a
     human approves; nothing is promoted by the model.
103. [pending] Combinatorial positions (the venue's conjunction tokens)
     assessed for conjunctive strategies and hedges; recorded, not traded.
104. [pending] Phase 20 report: simultaneous against per-bet Kelly on the
     backtests, health-state transitions on the paper record, the
     promotion criteria applied to every existing strategy.

## Phase 21: Scale proof and operations
Design: `docs/scaling.md` § 11 to 14. The capacity model becomes
measurements, and the platform becomes something one can operate.

105. [pending] Load tests with synthetic workspaces at the three scales of
     the capacity model against staging, recording every metric of the
     observability section; the first component to miss its objective is
     found and fixed; the numbers published.
106. [pending] Stage B: web, worker and ingest as separate services; Redis
     for limits and cache; a read replica; monthly partitions archived to
     object storage with chain hashes; the same handlers.
107. [pending] Queue and stream decision on measured claim latency and
     message rate; migration behind the existing interfaces if needed.
108. [pending] Cost per user-day measured and shown to the operator by
     component; budget and tier defaults revisited on the numbers. The same
     image published as a single-workspace, self-hostable build for
     developers who bring their own keys and accept the sources' terms
     themselves (F9); it is not the product's path for users.
109. [pending] Disaster recovery drill, incident runbooks, on-call, status
     page, abuse controls exercised.
110. [pending] Privacy and compliance: export and delete per workspace
     tested; data retention enforced; the terms and notices reviewed.
111. [pending] Phase 21 report: objectives attained per scale, the growth
     path's trigger metrics with current values.

## Phase 22: Hosted live execution (gated)
Design: `docs/security.md` version 2, agreed before any code, replacing the
keyring section with the hosted model and keeping everything else. The
safety layer of Phase 11 (`vp/live/`) is the base. Live execution is
available only to strategies that passed the promotion protocol and only in
jurisdictions the venue serves.

112. [pending] Security design version 2.
     - Key model, with a recommendation to decide: (A) the venue's session
       keys, a delegated signer the user authorises on the venue, scoped to
       trading, unable to withdraw, expiring in 180 days, revocable by the
       user at any time independently of us, held by the platform under
       envelope encryption in the key-management service; (B) browser
       signing with the user's wallet per order, which cannot run a
       scheduled strategy; (C) a signer the user runs locally that polls
       approved proposals. Proposed: A for execution, B for mandate commits
       and high-value approvals.
     - Threat model: server compromise, insider, prompt injection through
       evidence, dependency compromise, key exfiltration, a wedged worker,
       venue outage; the control for each.
     - Mandate: caps, universe (domains, kinds, liquidity floors), consent
       provenance and expiry; written by one function no tool can reach,
       only from the web surface with a consent token the model never
       produces; a proposal is not a mandate.
     - Order gate, fail-closed, in fixed order: mandate, expiry, halts,
       account binding, intent parse, positions and balance read from the
       venue, caps; structural breach denies, quantitative breach pauses for
       re-authorisation; a crash-safe pending-action marker per order;
       reconciliation against the venue's positions on restart.
     - Three halts: the user's (revoke the session key on the venue, or the
       app's halt), the workspace's, the platform's; cancel-all on halt,
       flatten only if the mandate says so.
     - Audit: proposal, approval, signed order (hash, never the signature),
       venue response, fill, settlement, each a ledger entry through the
       redaction filter; daily copy to write-once storage.
     - Jurisdiction gating; the builder attribution decision; fees from the
       market's schedule at match time; pUSD and approvals through the
       relayer.
113. [pending] Execution adapter on CLOB v2: the session-key signer, L1 and
     L2 authentication, limit and post-only orders at our price (never a
     market order), the user WebSocket channel for order and fill events,
     trade identifiers, reconciliation with the Data API; the paper and live
     paths identical except the signer and the environment, which are
     structurally different credentials.
114. [pending] Approvals through channels for orders above a mandate
     threshold; expiring, single-use, attributable.
115. [pending] Canary: one domain, one promoted strategy, the venue's
     minimum stake, a fixed number of settlements, total exposure of a few
     dollars; the mandate widened only by a new version after the canary
     ledger is read.
116. [pending] Live views: per-strategy live P&L and skill, live against
     paper divergence (fills, slippage, fees), the audit ledger.
117. [pending] External security review before live execution is offered
     beyond the canary workspace.
118. [pending] Polymarket US assessment: a separately regulated venue with
     its own API and fee coefficients; whether and how to add it as a second
     venue for users it serves; a decision, not code.
119. [pending] Phase 22 report.

## Phase 23: Documentation site, research lab and community (continuous)
Design: `docs/site.md`. A public site as detailed and as useful as
Vibe-Trading's wiki, in a visual style of our own to be decided, built from
the same `docs/` sources this repository already keeps, so that the docs a
developer reads and the docs a user reads are one text. Static, versioned,
searchable, reproducible.

120. [pending] Structure: **Home** (what it is, one honest example, install
     for developers, open the app for everyone); **Docs**, versioned by
     release with client-side search and an "on this page" outline: getting
     started, core concepts (a contract, a price as a forecast, cutoffs,
     proper scores, skill, Kelly, fees), the strategy spec, forecasters and
     committees, the evidence archive, paper trading, security, reference
     (CLI, API from the OpenAPI document, MCP tools, glossary, run card
     fields, the ledger format); **Tutorials**, hands-on and written for
     someone with no finance or programming background, including a
     day-by-day learning route from "just watch a market" to "write a
     strategy in a sentence" and "read your own record"; **Signals**, the
     library with each signal's formula, references, gates passed and live
     bench, generated from the registry manifest; **Research Lab**, long-form
     studies whose every number is one command away, with a caveats section
     as long as the findings; **Learn**, the in-app pages, published here
     too; **Changelog** and the phase reports.
121. [pending] Build: generated from `docs/` markdown and the registry and
     OpenAPI manifests by a small, dependency-light generator run in CI; no
     build step for the content author; math rendered; every page carries
     its source path and last-verified date; `llms.txt` and per-page
     markdown endpoints so agents read it as easily as people; an anonymous
     first-party visit counter at most.
122. [pending] Visual style: the default is the "paper" style recorded in
     `docs/site.md` (the app's Instrument Sans and JetBrains Mono, a warm
     off-white and a near-black theme, one teal accent, hairline rules
     instead of boxes, a 68-character measure, charts drawn inline in the
     theme's colours, no hero imagery), adopted as a placeholder so the site
     can be built now; the alternatives listed there are trialled later
     behind the same tokens, and no asset, layout or copy of Vibe-Trading's
     wiki is reused.
123. [pending] Research Lab, first studies, each reproducible with one
     command: "Fee-aware baselines: does anything beat Polymarket in CS2,
     weather and EPL, 2025 to 2026?"; "The favourite-longshot bias on
     Polymarket football"; "How sharp is Polymarket's weather market against
     numerical weather prediction?"; "Committees against single elicitation:
     the forward record"; "How many settled markets does a claim of edge
     need?"
124. [pending] Docs kept in step: each phase's design page and report are
     pages; the glossary in the app and the site are one file; a CI check
     fails on a page whose commands no longer run.
125. [pending] Contribution pages: the signal checklist, the domain kit,
     the DCO decision, the security policy, the agent-contributor guide for
     AI-assisted contributions (safe checks, high-risk surfaces).
126. [pending] Community channels decided (a forum or a chat server, with
     the impostor warning the security policy needs), and a public roadmap
     that mirrors this plan's status tags.
127. [pending] The name gate of `docs/vibe_trading.md` § 9 in CI.
128. [pending] Test reports continue per phase with runtimes and live
     measurements; pre-commit hooks pass on every commit.
129. [pending] Phase 23 report: pages, search quality, reproduction checks
     passing, visitor counts if counted.

## Deferred
- Kalshi as a second venue. Not in scope for the foreseeable future. The
  archived `src/collectors/kalshi.py` and the `KXCSGOGAME` and
  `KXENGLISHPREMIERLEAGUE` series tickers are the starting point if this is
  revisited.
- Polymarket US, a separately regulated venue: assessed in Phase 22, task
  111.
- Short-horizon crypto price markets and perpetuals on the venue: not
  pursued (Phase 17, task 79).
- Trading combinatorial positions: recorded in Phase 20, task 103; not
  executed.
- An MCP client that lets the research agent call external tools inside a
  backtest: rejected by principle 5; reconsidered only for the forward loop.

## Decisions, by phase

Decided on 2026-09-19: each proposal below was examined and adopted as
proposed, with two made concrete (the host and region in decision 1, a
minimum-edge default in decision 6). The flags that came out of examining
them follow the table and are part of the decision record; a flag marked
**gating** must be resolved inside the phase it names before that phase is
called done.

| Phase | Decision | Decided |
| :--- | :--- | :--- |
| 13 | Hosting provider and region | Fly.io (machines for web, worker and ingest; managed Postgres; Tigris object storage), first region Amsterdam, confirmed by flag F1 before anything else is built; stage A of `docs/scaling.md` |
| 13 | Who operates budgets and abuse | the repository owner; an operator role exists from day one so it can be handed over (F2) |
| 13 | Identity provider | email magic link now, OpenID Connect when a team asks (F3) |
| 13 | Prepare for the venue's builder programme now | no; decided with Phase 22 (F4) |
| 14 | Fees in Simple mode | yes, in cents, since the venue charges takers on sports and weather (F5) |
| 15 | Sizing defaults and the override whitelist | fraction 0.25, cap 5% of bankroll, a minimum edge of 0.03 after fees, absolute caps set by the workspace; a prompt may lower any of them and raise none (F6) |
| 15 | Whether the LLM forecaster ever sees the market price | only as an explicit belief option, labelled on every run card, never by default (F7) |
| 15 | Default model tiers and the $5 budget | a cheap tier for breadth, the expensive tier on demand; the budget revisited on Phase 21's cost numbers (F8) |
| 17 | Evidence sources and their licences per domain | evaluated in the design page; nothing scrape-hostile; commercial terms checked for each (F9) |
| 17 | The order in which new domains open | by data availability and market count, listed in the design page, each with a report before it is shown to users (F10) |
| 18 | Developer Certificate of Origin for external contributions | yes, once contributions are invited (F11) |
| 22 | The live key model | session keys for execution, browser signing for consent (F12) |
| 22 | Polymarket US | assess only (F13) |
| 23 | The site's visual style | the "paper" default of `docs/site.md` as the placeholder; alternatives trialled later (F14) |

### Flags recorded with the decisions

- **F1 (gating, Phase 13). Region and access must be lawful, not merely
  unblocked.** The rule, set by the owner on 2026-09-19: the platform abides
  by the venue's terms of service and by the law of the place it runs and
  of the places its users are. Concretely: the host region is one where the
  venue lawfully serves its public API, chosen for that reason and never to
  evade a restriction that applies to the platform or a user; access goes
  through the public, documented APIs under the venue's terms (rate limits
  honoured, no scraping of pages, no circumvention of any block), and the
  terms are read for what they say about automated access, storing and
  redistributing market data, and commercial use before the first
  production request; a user's own jurisdiction is attested at sign-up and
  checked again before live execution, which is offered only where the
  venue serves that user (F13); paper trading is play money and not a
  wager, and the terms of use say so. The first task on the host confirms
  from its region that the endpoints the platform uses are served and
  records the terms review in the Phase 13 report; a written legal opinion
  is obtained before public sign-up (Phase 14, task 48) and again before
  live execution (Phase 22, task 117). Amsterdam is the first candidate,
  not a certainty.
- **F2 (Phase 13). One operator is one point of failure.** The platform
  halt, budget changes and abuse responses all rest on one person until the
  operator role is granted to a second; a written hand-over procedure and a
  second operator are due before public sign-up (Phase 14, task 48).
- **F3 (Phase 13). Magic links need deliverable email.** A transactional
  email provider with the domain authenticated (SPF, DKIM, DMARC) is a
  hidden dependency and a small cost; sign-in emails are rate-limited per
  address and per IP, links are single-use and short-lived, and sessions
  are bound to the browser that requested them.
- **F4 (Phase 22). The builder programme may matter for wallets.** The
  venue's SDK creates deposit wallets for new users through builder
  credentials and attributes volume through a builder code; Phase 22's
  design decides whether users bring a wallet or the platform helps create
  one. Nothing in Phase 13 precludes either.
- **F5 (gating, Phase 13). Paper trading charges no fees today; it will
  use the backtest's fee model, one implementation.** `vp/paper/loop.py`
  orders at the touch with no fee term, and the backtest default is zero,
  so every paper P&L to date is optimistic. Decided 2026-09-19: the market
  record carries each market's `feeSchedule` as captured with the snapshot;
  the one fee function in `vp/backtest/sizing.py` computes the taker fee
  $C \cdot r \cdot p(1-p)$ for backtest fills and paper fills alike; a paper
  order records the fee it paid and the effective price; settlement P&L is
  net of it; and the run card and the ledger show fees paid. This lands in
  Phase 13 (task 37) so that the first hosted paper cycle is realistic, and
  task 77 re-runs the Phase 9 baselines fee-aware. Paper orders have paid
  each market's own rate since 2026-09-23 (task 37); `taker_base_fee` is a
  legacy field and the rate is now read from `feeSchedule`.
- **F6 (Phase 15, then 20). Per-market caps are not portfolio caps.** Until
  Phase 20 adds per-event exposure and simultaneous Kelly, several positions
  in one event (a winner market and its maps, the buckets of one weather
  day) can together exceed the risk the 5% cap suggests; the preview says
  so. The 0.03 minimum edge is a tunable, chosen because the Phase 9 report
  found a 5% threshold removed every climatology bet and a zero threshold
  lost the bankroll to the spread; it is revisited with the fee-aware
  baselines.
- **F7 (Phase 15). A belief that sees the price scores near par.** A run
  whose belief was shown the market price is labelled on its run card and
  excluded from the leaderboards' skill rankings, because its skill against
  the market measures anchoring, not information. Signals and blends use
  the price legitimately and say so in their metadata.
- **F8 (Phase 15). A $5 budget is one small LLM backtest.** At $0.01 to
  $0.05 a forecast the budget buys 100 to 500 forecasts a month; a
  400-market backtest with an LLM belief can spend it in one run. The
  preview shows the cost first, LLM backtests default to a 100-market sample
  through the batch endpoint, and the memo cache makes repeated runs on the
  same markets free. Model identifiers are chosen at build time from the
  provider's current list, not fixed here.
- **F9 (gating, Phase 17). Free tiers are for non-commercial use; the
  shared archive pays for commercial terms.** Open-Meteo's free API is for
  non-commercial use and a hosted product with users needs its paid plan;
  football data providers' free tiers carry rate and redistribution limits;
  Liquipedia's API requires attribution and its share-alike licence covers
  its text, not the facts derived from it. The owner asked on 2026-09-19
  whether each user hosting their own instance would avoid this. It would
  not serve the product: the audience has no terminal (`docs/product.md`),
  every self-hosted instance would poll every source and the venue
  separately (against principle 4 and the venue's limits), and an archive
  only accumulates forward, so a personal archive started today has no past
  to backtest against; the shared archive, captured once from the first
  week of Phase 13, is the asset. Commercial terms for the shared sources
  cost tens of dollars a month and scale with the number of sources, not
  users, so the platform pays them. Two things are kept for people who do
  want their own: the local `vp` command line, which already runs on a
  laptop with the user's own keys, and a single-workspace image of the same
  platform that a developer can self-host with their own keys and terms
  (Phase 21, task 108). Each source's terms are recorded in the evidence
  design page before its collector runs against production, and the
  archive stores provenance so a source can be withdrawn with its rows.
- **F10 (Phase 17). Politics is a compliance domain, not only a data
  domain.** Opening it needs the jurisdiction notice and terms of Phase 14
  reviewed for it; it stays behind the other candidates.
- **F11 (resolved 2026-09-19). The repository is MIT-licensed.** The owner
  chose MIT; `LICENSE` names the copyright holder as configured in the
  repository's git identity (a full legal name can replace it at any time),
  `pyproject.toml` declares it, and `NOTICE` keeps the ported code's and the
  fonts' notices. Contributions (Phase 18) are accepted under it with the
  Developer Certificate of Origin.
- **F12 (gating, Phase 22). What a session key is, and what it cannot
  protect against.** On the venue, a user's money sits in a wallet that only
  the user's own key controls. A session key is a second key the user
  creates and authorises on the venue to trade on that wallet's behalf: it
  can place and cancel orders, it cannot move money out, the venue cancels
  its orders the moment the user revokes it, and it expires after 180 days.
  The platform would hold this second key (encrypted) and never the user's
  own, so a breach of the platform cannot steal funds. What it cannot
  prevent is losing money through trades themselves: a bug or a bad
  strategy could keep buying until the wallet is empty, because the venue
  does not cap how much the session key may trade. That is why the
  platform's mandate (caps per order, per market, in total and per day) is
  the only limit, and why the design requires three further things: the
  user funds a separate wallet with only what they are willing to risk, the
  canary runs at the venue's minimum stake, and the expiry is tracked so a
  strategy never stops silently. Session keys are a 2026 venue feature for
  its current wallet type; older wallet types may not support them, and the
  design checks this at the time.
- **F13 (Phase 22). United States users cannot trade live here.** The
  international venue does not serve them; paper trading is not money and
  is unaffected; live execution is gated by jurisdiction from the first
  order, and Polymarket US is a separate venue with its own API and fees to
  assess, not a fallback.
- **F14 (Phase 23). The default style passes its own checks.** The teal
  accent on the warm off-white background and its dark counterpart both
  clear WCAG AA contrast (about 5.8:1 and 7.4:1); any trialled alternative
  must clear the same bar before it is shown.
- **F16 (decided 2026-09-23). No cloud account until the end.** The owner
  chose to build without a Fly.io account and deploy last. Everything is
  built and verified against a local stand-in (Postgres 16, an
  S3-compatible store, the same image). Three things cannot be done until
  the deploy, and are listed so they are not forgotten: the region probe
  and terms check of F1 from the host's region; the restore drill and
  every measurement of task 38 that needs a real host (request latency
  from outside, ingestion lag over days, cost per user-day); and anything
  a real user touches, since public sign-up (Phase 14) needs a host.
  Phase 21, the scale proof, needs a staging environment and is therefore
  the latest point the deploy can happen; Phase 22 depends on it too.
  **The cost:** the evidence archive of task 33 only accumulates while a
  collector runs continuously, and a development container is ephemeral,
  so without an always-on machine nothing is captured between sessions and
  those weeks are lost to every future backtest. Decided the same day:
  everything runs on the development machine until the end, collectors
  included, so evidence is captured only while a session is running and
  the gaps between sessions are accepted. Running the collectors alone on
  an always-on machine remains available at any time and writes the same
  files.
- **F15 (resolved 2026-09-19). Live execution is hosted only, and
  built last.** The owner decided that trades must execute while the
  user's computer is closed, so the operator-machine path of Phase 11
  (tasks 23 and 24) is superseded by Phase 22, and Phase 22 is built after
  every other numbered phase, including the scale proof. `docs/security.md`
  is the base for the design's version 2. The invariant stands until that
  version is agreed: no order-signing code anywhere.
