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
  data flow and design decisions; `docs/data_layer.md` the record, domains,
  dataset and snapshots.
- `vp/`: the package. `venues/polymarket.py` (read-only client with the
  closed-is-not-resolved evidence ladder), `domains/` (cs2, weather, epl),
  `markets/` (record, source, Parquet store, dataset, snapshot),
  `backtest/bankroll.py`, `cli.py` (`vp build-dataset`, `vp snapshot`).
- `tests/`: offline tests only; `tests/reports/` has a report per phase with
  runtimes. `data/` is git-ignored.

## State at handoff (2026-09-13)

Phases 6 and 7 are complete, including the live measurement (task 8), which
ran from a container with access to Polymarket on 2026-09-13. Its results
are in `tests/reports/phase7_data_layer.md` and `docs/data_layer.md`: the
Gamma tag ids for all three domains are recorded in `vp/domains/`, the
parsers were corrected to the question forms the venue actually serves, the
catalogue pager handles Gamma's 100-row and 2000-offset caps, and price
histories fall back from hourly to daily bars because the venue keeps
sub-daily bars only for about a month.

Things a future session should know:

- The resolved sets are large (13k EPL, 89k CS2, 134k weather labelled
  markets) and dominated by props (over/under, handicaps, exact scores) that
  parse to no fields. Match, season and daily-temperature markets are the
  parsed subsets a forecaster can use; see the kind counts in the report.
- `uv run vp build-dataset --domain <d> --no-history` takes 20 s to 2 min per
  domain; with histories it is one request per market at 0.35 s spacing.
- The next step is Phase 8 (forecasters). Ask for the go-ahead before
  starting it.

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
