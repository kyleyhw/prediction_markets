# Phase 7 Test Report: Data Layer

Date: 2026-09-12. Environment: Python 3.14.0rc2 via `uv 0.8.17`, Linux
container without access to Polymarket. Total runtime of all checks below:
about 5 s wall.

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

`uv run pytest -q`: 36 passed in 0.34 s (0.83 s wall). The 20 Phase 6 tests
still pass; the 16 new ones are below.

### `tests/test_domains.py`

**What.** Membership and parsing for all three domains.

**Why.** Membership decides what enters the dataset, and parsed fields are
what the forecasters and the weather baselines will consume; both must hold
on the venue's real phrasing.

**Test data.** Question strings copied from the archived December 2025
reports: the CS2 match title `Counter-Strike: Spirit vs Team Falcons (BO3)`
and tournament question `Will FURIA win the StarLadder Budapest Major 2025?`;
the three weather bucket forms (`between 54-55°F`, `53°F or below`,
`62°F or higher`), three record-rank forms and the global anomaly form; and
EPL forms by analogy with the recorded Bundesliga question. Negative cases
are the archived project's own false positives: `major ground offensive`
against CS2's former `Major` keyword, and `Miami Heat` against weather.

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

**Test data.** One EPL event with five markets covering every classification:
resolved with winner Yes, resolved with winner No, resolved void, closed but
pending, and still open. The fake returns that event both from the tag page
and from every keyword search, so de-duplication is exercised. One CS2 event
and one unrelated Fed event check domain filtering. The fake history returns
an empty series for one token and raises for another, so the report's empty
and error counts are both non-trivial.

## Live Measurement

Task 8's retrievability measurement, whether resolved markets and their
histories are actually served, was not run. The container's egress proxy
denies connections to `gamma-api.polymarket.com` and `clob.polymarket.com`
(see the Phase 6 report). The command to run from a machine with access:

```bash
uv run vp build-dataset --domain epl --max-markets 20
```

Its printed report is the measurement. Two further things that run will
settle: the Gamma tag ids for CS2 and weather, and whether the EPL match
question forms match the parser.
