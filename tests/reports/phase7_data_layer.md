# Phase 7 Test Report: Data Layer

Date: 2026-09-12, live measurement added 2026-09-13. Environment: Python
3.14.0rc2 via `uv 0.8.17`, Linux container; the 2026-09-13 session had
access to Polymarket. Total runtime of the offline checks below: about 5 s
wall; of the live runs, about 8 minutes.

## Purpose

Phase 7 added the typed market record, the three domain adapters, the
Polymarket source, Parquet storage, the resolved-market dataset builder and
the snapshot collector. The checks verify the invariants later phases rely
on: that the settlement label follows the first outcome and is never set from
a price, that domain membership admits and rejects the right markets, that
the parsers read the recorded question forms, that records survive a Parquet
round trip unchanged, and that the dataset and snapshot builders classify,
de-duplicate and write what they claim.

## Static Checks

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .` and `ruff format --check .` | passed, 31 files | < 1 s |
| `ty check` (`error-on-warning`) | passed, 0 diagnostics | < 1 s |
| `detect-secrets` | passed, no findings | < 1 s |
| `pre-commit run --all-files` | all four hooks passed | 4.0 s |
| `vp --help` | lists `build-dataset` and `snapshot` | < 1 s |

Test files are exempt from the line-length rule so fixture question strings
can be kept verbatim.

## Unit Tests

`uv run pytest -q`: 39 passed in 0.33 s (0.8 s wall) after the 2026-09-13
changes. The 20 Phase 6 tests still pass; the Phase 7 ones are below, with
the cases added on 2026-09-13 from live question strings noted.

### `tests/test_domains.py`

**What.** Membership and parsing for all three domains.

**Why.** Membership decides what enters the dataset, and parsed fields are
what the forecasters and the weather baselines will consume; both must hold
on the venue's real phrasing.

**Test data.** Question strings copied from the archived December 2025
reports and, since 2026-09-13, from the live catalogue. CS2: the current
match title with format and stage (`Counter-Strike: Rare Atom vs DEPO (BO3)
- Asia Championships Closed Qualifier Playoffs`), a per-map winner whose
format comes from the event title, the 2024 `ESL Counter-Strike
Quarterfinals: G2 vs Liquid` form, `CS: Sashi vs HOTU`, two tournament
forms, and three props under a match event that must parse to nothing.
Weather: the three archived bucket forms, the live one-degree form, an en
dash range and a range without "between", three record-rank forms and the
global anomaly form. EPL: the current and the 2024 season-winner forms, the
current `win on <date>` and `end in a draw?` match forms, the 2024 `win
against`, `be a draw` and `match between` forms, and an over/under prop
that must parse to nothing. Negative membership cases: the archived
project's false positives (`major ground offensive`, `Miami Heat`), the
Esports label (which no longer admits, being shared with every game), a
2024 Champions League tie under tag 306, a Champions League qualification
market under tag 82, and a Women's Super League fixture.

### `tests/test_schema_store.py`

**What.** Label derivation in `market_from_record`, rejection of non-binary
markets, and Parquet round trips for markets (with books, tags and parsed
fields) and histories.

**Why.** The label $y$ is the quantity every score depends on; the Parquet
schema is the contract between phases.

**Test data.** A resolved Yes/No record whose winner is "No", so the label is
0 and the test cannot pass by defaulting to 1; the same record with winner
"Yes", with no winner (void), and pending with only an implied winner, which
must all give the expected label or `None`. A three-outcome record and an
empty question for rejection. An empty market list, to check the schema is
written even with no rows.

### `tests/test_dataset.py`

**What.** Discovery de-duplication and filtering, the dataset builder's
classification counts and files, the `max_markets` cap, and snapshot book
attachment, all against a fake source that serves fixture events.

**Why.** These are the code paths a live run exercises, and they cannot be
run live here; the fake reproduces the client's record shapes exactly so the
logic is tested even though the transport is not.

**Test data.** One EPL event with six markets covering every classification:
resolved with winner Yes (twice), resolved with winner No, resolved void,
closed but pending, and still open. The fake returns that event both from
the tag page and from every keyword search, so de-duplication is exercised.
One CS2 event and one unrelated Fed event check domain filtering. The fake
history returns an empty series for one token at every bar width, raises for
another, and serves a third only at daily bars, as the venue does for older
markets; the test asserts the exact sequence of bar widths requested, the
`bar_minutes` stored, and the per-bar count in the report.

### `tests/test_polymarket.py` (addition of 2026-09-13)

**What.** `iter_events` against a fake catalogue of 2,300 events.

**Why.** Gamma rejects offsets above 2,000, which the live tags exceed; the
walk must restart from the last end date and yield every event exactly once.

**Test data.** Events with ten per end-date second, so the boundary date is
shared by several events and the skip-by-id path is exercised; the fake
asserts no request crosses the cap.

## Live Measurement (2026-09-13)

The container's proxy allowed `gamma-api.polymarket.com` and
`clob.polymarket.com`, so the measurement deferred from Phase 6 ran. Every
command below is reproducible with the package as committed; data went to a
scratch root and is not in the repository.

### Quick check, 20 markets per domain with histories

`uv run vp build-dataset --domain <d> --max-markets 20`, first run of the
day, before any code change:

| Domain | Seen | Labelled | Histories | Empty | Errors | Runtime |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| epl | 20 | 20 | 20 | 0 | 0 | 11 s |
| cs2 | 20 | 20 | 19 | 1 | 1 | 31 s |
| weather | 20 | 20 | 20 | 0 | 0 | 13 s |

The one error was a 20 s read timeout on `prices-history`; the same request
answered in about a second when retried twice, so it was transient and is
left to the run's per-market error handling. The one empty series is a 2024
match market with no recorded trades.

**Result.** Resolved markets are served, with the CLOB `winner` flag or a
final `umaResolutionStatus` present, and their histories are served. The
archived project's 400/404 responses did not recur on any of the endpoints
used here.

### What the quick check exposed

Reading the twenty records per domain showed four things the offline tests
could not:

1. **Question forms.** The EPL match parser's guessed forms were wrong in
   every case (the venue writes `Will Arsenal FC win on 2026-09-19?` and
   `Will A vs. B end in a draw?`), the season form has a `(EPL)
   Championship` suffix, weather has a one-degree bucket with no range word,
   and CS2 titles carry a stage prefix or suffix and a `Map N Winner`
   suffix that the old parser left inside the team names. All parsers were
   rewritten from the live strings; the CS2 and EPL parsers now read the
   question only, because props under a match event (`Games Total: O/U
   2.5`) were being parsed as the match from the event title.
2. **Tag ids.** Recorded from the `tag_ids` of discovered events for all
   three domains (see `docs/data_layer.md`). Tag 306 (EPL) had been applied
   in 2024 to Champions League ties, so other competitions are now excluded.
3. **History bar width.** With the default daily bars, a two-day weather
   market has two points. Probing `fidelity` showed the venue serves hourly
   and finer bars only for markets closed within about a month (present for
   2026-08-13, absent for 2026-08-07 and every earlier date sampled back to
   2023, where daily bars are still served). `history()` now tries hourly
   then daily and records the bar width.
4. **Catalogue caps.** `limit` is truncated to 100 and `offset` above 2000
   returns HTTP 422 (`offset too large, use /events/keyset`). The keyset
   endpoint returns a `next_cursor` but none of fourteen parameter names
   continued from it; `end_date_min` with `order=endDate` works, so the
   pager restarts from the last end date at the cap.

### Full discovery, all closed markets, no histories

`uv run vp build-dataset --domain <d> --no-history`, after the changes:

| Domain | Seen | Labelled | Void | Pending | Open | Runtime |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| epl | 13,071 | 12,716 | 0 | 36 | 319 | 20 s |
| cs2 | 99,473 | 88,668 | 10,680 | 7 | 118 | 69 s |
| weather | 134,303 | 134,077 | 2 | 57 | 167 | 120 s |

"Open" counts markets still trading inside events the closed filter
returned. Parsed kinds and labels in the labelled sets:

| Domain | Parsed kinds | Unparsed (props) | Label $y=1$ |
| :--- | :--- | ---: | ---: |
| epl | match 2,482; season_winner 30 | 10,204 | 26% |
| cs2 | match 25,293 (incl. per map); tournament_winner 919 | 62,456 | 43% |
| weather | daily_temperature 131,262; global_anomaly 135; record_rank 37 | 2,643 | 10% |

Of 131,285 daily-temperature questions, 23 fail to parse; all are malformed
early-2025 forms. The unparsed remainder are over/under, handicap, exact
score and odd/even props (EPL, CS2) and tornado, rain, earthquake and
drought questions (weather). By end year the sets are 2024 to 2026 for EPL
and CS2 and almost entirely 2026 for weather; the low base rate in weather
comes from the ten-bucket structure of a daily temperature event.

### Histories after the fallback change

`uv run vp build-dataset --domain weather cs2 epl --max-markets 20` (68 s):
20 of 20 histories served per domain, none empty, no errors, all at daily
bars because the end-date walk now yields the oldest markets first. Sampling
three EPL and two weather markets per end month from the full sets gave
hourly bars for every market closed on or after 2026-08-13 and none before.

### Snapshot

`uv run vp snapshot --domain cs2 weather epl --depth 5 --max-markets 10`:
10 markets per domain written with five levels per side in 32 s. One book
request returned 404 for a listed token on a CS2 market not yet trading; the
quote was kept without a book, as designed.
