# vibe-predict: project context for Claude sessions

Read this first; it carries the state a fresh session does not have. The
user's global conventions apply on top of it. Key project-specific ones: work
directly on `master` (no branches unless experimenting), commit and push
often, no Claude or Anthropic attribution anywhere, ask before starting each
plan phase, and keep code minimal with full reasoning in docs.

## What this is

An LLM forecaster for binary Polymarket contracts in three domains (CS2
esports, weather, English Premier League), scored first by backtest against
resolved markets, then by paper trading, with live execution planned but
gated on a security design that is not yet agreed. Polymarket is the only
venue for the foreseeable future; Kalshi is deferred. The LLM forecaster is
the point of the project, in the spirit of HKUDS/Vibe-Trading, which was
reviewed and partly ported (see `docs/provenance.md`, `NOTICE`).

The original `prediction_markets` project is archived unchanged under
`archive/prediction_markets/` and excluded from tooling. Do not delete it.

## Where things are

- `PROJECT_PLAN.md`: phases 1–5 are the archived project; 6–12 are this one.
  Status tags are kept current; update them as tasks finish.
- `README.md`, `docs/index.md`: entry points. `docs/architecture.md` has the
  data flow and design decisions; then one page per phase:
  `data_layer.md`, `forecasters.md`, `scoring.md`, `sizing.md`,
  `paper_trading.md`, `security.md`.
- `vp/`: the package. `venues/polymarket.py` (read-only client with the
  closed-is-not-resolved evidence ladder), `domains/` (cs2, weather, epl),
  `markets/` (record, source, Parquet store, dataset, snapshot),
  `forecast/` (evidence, baselines, Elo, LLM, registry), `backtest/`
  (scoring, sizing, simulator, runner, bankroll), `paper/` (ledger, loop,
  leakage), `cli.py` (`vp build-dataset`, `vp snapshot`, `vp backtest`,
  `vp paper`).
- `tests/`: offline tests only; `tests/reports/` has a report per phase with
  runtimes. `data/` is git-ignored.

## State at handoff (2026-09-13, evening)

Phases 6 to 10 are complete and Phase 12's continuous items are in place;
Phase 11 has its security design proposed in `docs/security.md` and is
waiting for the user to agree to it before any execution code is written.
Each phase has a report in `tests/reports/` with what was measured live.

What exists, in order of the data flow: the Polymarket client and data
layer (`vp/venues`, `vp/markets`, `vp/domains`); forecasters behind a
cutoff-bounded `Evidence` object (`vp/forecast`: market price, constant,
climatology, Elo, and the LLM forecaster on the official Anthropic SDK);
scoring, sizing, the fill simulator and `vp backtest` (`vp/backtest`); and
paper trading on a hash-chained ledger with settlement and the leakage
check (`vp/paper`, `vp paper run|settle|leakage`).

Things a future session should know:

- The LLM forecaster has never been run against the API: the container
  holds no credentials. `LLMForecaster()` builds a client from the
  environment, so the first keyed run needs only the key, and
  `vp backtest --forecasters market llm --max-markets 50` on a domain is
  the first thing to do with it. The cost per forecast is printed.
- Live baseline results (Phase 9 report): no baseline beats the market.
  Weather climatology has skill −0.19 against it, EPL Elo −0.02 (at par a
  day out) and CS2 Elo −0.12; every simulated strategy loses at a 5%
  minimum edge. That is the bar the LLM forecaster has to clear.
- Evidence comes from the resolved dataset itself (resolutions as results
  and realised buckets). Open-Meteo's archive and previous-runs endpoints
  were rate-limited from the container; wiring them in is the obvious
  next step for weather.
- Known follow-up: `vp paper run --max-markets N` caps the snapshot, not
  the parsed markets, so a small N can yield nothing to forecast in EPL.
- `data/` is git-ignored; a session starts with no datasets. Rebuilding:
  `vp build-dataset --domain <d> --no-history` (20 s to 2 min), then
  histories for the markets to be backtested (about one per second).
- The SessionStart hook refreshes `uv` (the container's is too old to
  install the pinned Python 3.14.7) and sets the git identity to the
  repository owner. Commits must carry that identity and no assistant
  attribution.
- Work was pushed to the branch the web session was given; merging into
  `master` is the user's call.

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
