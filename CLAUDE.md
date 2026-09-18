# vibe-predict: project context for Claude sessions

Read this first; it carries the state a fresh session does not have. The
user's global conventions apply on top of it. Key project-specific ones: work
directly on `master` (no branches unless experimenting), commit and push
often, no Claude or Anthropic attribution anywhere, ask before starting each
plan phase, and keep code minimal with full reasoning in docs.

## What this is

A platform on which people implement their own forecasting strategies for
binary Polymarket contracts through conversation with an LLM, in three
domains (CS2 esports, weather, English Premier League). The platform is
the aim, not any particular edge: it supplies the data, the cutoff-safe
evidence, the scoring, the backtest, paper trading, a dashboard and,
behind an agreed security design, live execution, so that a strategy
described in conversation can be built, scored honestly against the market
and run. The baseline results it reports (no baseline beats the market)
are the benchmark it offers, not a target it has failed. Polymarket is the
only venue for the foreseeable future; Kalshi is deferred. The LLM
forecaster is the central component, in the spirit of HKUDS/Vibe-Trading,
which was reviewed and partly ported (see `docs/provenance.md`, `NOTICE`).

The original `prediction_markets` project is archived unchanged under
`archive/prediction_markets/` and excluded from tooling. Do not delete it.

## Where things are

- `PROJECT_PLAN.md`: phases 1–5 are the archived project; 6–12 are the
  engine and dashboard; 13–16 are the hosted app for everyone
  (`docs/product.md`). Status tags are kept current; update them as tasks
  finish.
- `README.md`, `docs/index.md`: entry points. `docs/architecture.md` has the
  data flow and design decisions; then one page per phase:
  `data_layer.md`, `forecasters.md`, `scoring.md`, `sizing.md`,
  `paper_trading.md`, `security.md`, `ui.md`.
- `vp/`: the package. `venues/polymarket.py` (read-only client with the
  closed-is-not-resolved evidence ladder), `domains/` (cs2, weather, epl),
  `markets/` (record, source, Parquet store, dataset, snapshot),
  `forecast/` (evidence, baselines, Elo, LLM, registry), `backtest/`
  (scoring, sizing, simulator, runner, bankroll), `paper/` (ledger, loop,
  leakage), `live/` (safety layer only), `ui/` (read-only dashboard),
  `cli.py` (`vp build-dataset`, `vp snapshot`, `vp backtest`, `vp paper`,
  `vp ui`).
- `tests/`: offline tests only; `tests/reports/` has a report per phase with
  runtimes. `data/` is git-ignored.

## State at handoff (2026-09-18)

Phases 6 to 10 and 12 are complete; Phase 11 has its security design
proposed in `docs/security.md` with the safety layer built and tested in
`vp/live/` (nothing there can sign or send an order), waiting for the user
to agree the design before the execution adapter (task 23) is written.
Each phase has a report in `tests/reports/` with what was measured live.

Direction set on 2026-09-18 (`docs/product.md`, Phases 13–16 in the plan):
the product becomes a hosted web app for people with no technical
background, with no terminal for users; developers and the operator keep
the command line. Phase 13 (service, accounts, per-user state, jobs,
deploy, product-paid LLM budgets) is next and **needs the go-ahead**, plus
two decisions listed in `docs/product.md`: hosting provider and region, and
who operates budgets and abuse. Phase 15, strategies from conversation,
gets its own design page (`docs/strategies.md`) before any code; the
user wants sizing defaults that a prompt can override, and per-strategy
P&L views. The domains will open up beyond CS2, weather and EPL; do not
hard-code the three anywhere new, and the repository description no
longer names them.

What exists, in order of the data flow: the Polymarket client and data
layer (`vp/venues`, `vp/markets`, `vp/domains`); forecasters behind a
cutoff-bounded `Evidence` object (`vp/forecast`: market price, constant,
climatology, Elo, and the LLM forecaster on the official Anthropic SDK);
scoring, sizing, the fill simulator and `vp backtest` (`vp/backtest`,
which also writes `results.json` per run); paper trading on a hash-chained
ledger with settlement and the leakage check (`vp/paper`); the live safety
layer (`vp/live`); and the dashboard (`vp ui`: standard-library server, one
hand-written page, vendored Instrument Sans and JetBrains Mono, charts
drawn in the page, a glossary that makes every term clickable; read-only by
design, see `docs/ui.md`).

Things a future session should know:

- The LLM forecaster has never been run against the API: the container
  holds no credentials. `LLMForecaster()` builds a client from the
  environment, so the first keyed run needs only the key, and
  `vp backtest --forecasters market llm --max-markets 50` on a domain is
  the first thing to do with it. The cost per forecast is printed.
- Live baseline results (Phase 9 report): no baseline beats the market
  (weather climatology skill −0.19, EPL Elo −0.02, CS2 Elo −0.12). Edge is
  not the goal; these are the benchmark a user's strategy is measured
  against.
- Evidence comes from the resolved dataset itself. Open-Meteo's archive and
  previous-runs endpoints were rate-limited from the container; wiring them
  in is the obvious next step for weather.
- Known follow-up: `vp paper run --max-markets N` caps the snapshot, not the
  parsed markets, so a small N can yield nothing to forecast in EPL.
- `data/` is git-ignored; a session starts with no datasets. Rebuilding:
  `vp build-dataset --domain <d> --no-history` (20 s to 2 min), then
  histories for the markets to be backtested (about one per second).
- The SessionStart hook refreshes `uv` (the container's is too old for the
  pinned Python 3.14.7) and sets the git identity to the repository owner.
  Commits carry that identity and no assistant attribution.
- Checking the dashboard visually: run `vp ui` on a data root, then
  Playwright with the preinstalled Chromium
  (`executable_path="/opt/pw-browsers/chromium"`, `args=["--no-proxy-server"]`,
  because the container's proxy otherwise breaks localhost subresources),
  via `uv run --with playwright`. Put server start and stop in a script
  file: a `pkill -f "vp ui"` typed inline matches the shell running it.
- `master` is kept fast-forwarded to the session branch at the user's
  request; work on `master` directly when the session allows it.

## Invariants to preserve

- A market's label `resolved_outcome` is set only from settlement evidence
  (CLOB `winner` flag or a final oracle status), never from a price. Closed
  is not resolved.
- The first outcome of every record is the event being forecast; forecast,
  market price and label all refer to it.
- Every forecaster will take an explicit information cutoff and must not
  read anything after it.
- Live execution code is not to be written until the security design in
  Phase 11 task 22 is agreed with the user.

## Commands

```bash
uv sync                          # environment (the SessionStart hook does this on the web)
uv run pytest -q                 # tests
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pre-commit run --all-files
```
