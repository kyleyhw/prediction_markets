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

## State at handoff (2026-09-12)

Phases 6 and 7 are complete except one item. The previous session ran in a
container whose network policy blocked `gamma-api.polymarket.com` and
`clob.polymarket.com`, so nothing has been run against the live API. Task 8
of Phase 7 is therefore `[in-progress]`: the retrievability measurement.

First actions for a network-enabled session, in order:

1. `uv run vp build-dataset --domain epl --max-markets 20` and read its
   report. It answers whether resolved markets and their histories are
   served. Then the same for `cs2` and `weather`.
2. Record the Gamma tag ids for CS2 and weather in `vp/domains/cs2.py` and
   `vp/domains/weather.py` (`tag_ids` is empty; labels are known). Find them
   from the `tag_ids` field of discovered events.
3. Check the EPL match question forms against `vp/domains/epl.py`; no EPL
   strings were ever captured, so the match parser is a guess. Fix the regex
   if the venue phrases them differently.
4. Run `uv run vp snapshot --domain cs2 weather epl --depth 5` once to
   confirm the book path.
5. Update task 8 to `[completed]` with what was measured, add the live
   results to `tests/reports/phase7_data_layer.md`, commit, push.
6. Then ask for the go-ahead on Phase 8 (forecasters). Do not start it
   without it.

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
