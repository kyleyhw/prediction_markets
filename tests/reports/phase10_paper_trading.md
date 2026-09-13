# Phase 10 Test Report: Paper Trading

Date: 2026-09-13. Environment: Python 3.14.7 via `uv 0.12.13`, Linux
container with access to Polymarket. Total runtime of the checks below:
about 40 s wall.

## Purpose

Phase 10 added the hash-chained ledger, the forward paper-trading cycle,
the settlement pass and the leakage check. The checks verify that the
ledger detects every kind of tampering, that a cycle orders at the real
touch for no more than the resting size and never twice on one market, that
settlement books profit and scores from the venue's winner flag, and that
the leakage statistic behaves.

## Static Checks

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .` and `ruff format --check .` | passed | < 1 s |
| `ty check` (`error-on-warning`) | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 6 s |

## Unit Tests

`uv run pytest -q`: 63 passed in 1.1 s. New files:

### `tests/test_ledger.py`

**What.** Chaining, verification, and detection of an edited payload, a
deleted entry and a swapped pair.

**Why.** The ledger is the only store of paper state and the design of the
live audit trail; a tamper it cannot see is a hole in the security design.

**Test data.** Three entries; each tamper is applied to the file text and
`verify()` must return sequence number 1, the first entry whose hash or
predecessor no longer matches; restoring the file verifies again.

### `tests/test_paper.py`

**What.** One cycle against the fake source of the dataset tests (one open
CS2 match with a one-level book), a second cycle, two settlement passes,
and the leakage gap.

**Why.** These are the code paths a scheduled run exercises unattended.

**Test data.** A constant forecaster believing 0.9 against an ask of 0.51:
quarter Kelly exceeds the 5% cap, so the stake is 5 of 100, which is 9.8
shares; the touch rests 7, so the fill is 7 shares for 3.57, checked by
hand. The market baseline declines (no stored history in the backtest
sense; in the live loop it uses the snapshot price). The second cycle
places nothing because the position is open. A fake market fetch answers
pending first, then resolved Yes: settlement books $7 - 3.57$, the Brier
score $(0.9 - 1)^2$, and the chain still verifies. The leakage gap between
Brier scores near 0.02 and near 0.25 has a bootstrap interval that
excludes zero.

## Live Cycle

`uv run vp paper run --domain cs2 weather epl --forecasters market constant
elo climatology --depth 3 --max-markets 15`, 27 s, then `vp paper settle`:

| Domain | Snapshotted | Parsed | Forecasts | Orders |
| :--- | ---: | ---: | ---: | ---: |
| cs2 | 15 | 15 | 15 (constant) | 1 |
| weather | 15 | 15 | 30 (constant, climatology) | 0 |
| epl | 15 | 0 | 0 | 0 |

The ledger holds 3 cycle, 45 forecast and 1 order entries and verifies.
Settlement found the one position pending, as expected minutes after
placement. What the run showed:

- Seven of the fifteen EPL markets the end-date walk reached first have no
  book yet (the CLOB answers 404 for their tokens; they are the newest
  2026-27 season markets), and none of the fifteen parsed, so a per-domain
  cap applied at the snapshot is the wrong place for it: the cap should
  count parsed markets. Recorded as a follow-up; a run without the cap
  snapshots every open market.
- The market baseline produced no forecast because open markets have no
  stored history; it now falls back to the snapshot price for a market
  still trading, which is what "the market's forecast at the present"
  means. Elo declined every CS2 market in the sample (tier-two teams with
  fewer than three results); climatology forecast all fifteen weather
  buckets and found no edge past the spread on any.
- The one order was the constant baseline buying the complementary share
  of a market priced at 0.999 for 0.001 a share, 50,000 shares for 50, the
  full 5% cap. It is the behaviour the sizing rule specifies for a belief
  of 0.5 against a near-certain price, and it is why the constant
  forecaster is a scale anchor and not a strategy.

The leakage check needs settled forward positions, which take days to
accumulate; the command runs and reports "no forecaster settled in both"
until then.
