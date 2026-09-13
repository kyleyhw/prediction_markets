# Phase 9 Test Report: Backtest Scoring

Date: 2026-09-13. Environment: Python 3.14.7 via `uv 0.12.13`, Linux
container with access to Polymarket. Total runtime of the checks below:
about 30 s of unit tests and static checks, plus the live runs listed with
their own times.

## Purpose

Phase 9 added proper scores and calibration, the fee and Kelly arithmetic,
the fill simulator and `vp backtest`. The unit tests pin each formula to a
hand calculation; the live runs score the baselines on real resolved
markets and are the first measurement of whether anything beats the
market.

## Static Checks

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .` and `ruff format --check .` | passed | < 1 s |
| `ty check` (`error-on-warning`) | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 6 s |

## Unit Tests

`uv run pytest -q`: 63 passed in 1.1 s. New files:

### `tests/test_scoring.py`

**What.** Brier and log scores on known values, skill, and the Murphy
decomposition.

**Why.** The decomposition is an identity; if the code does not satisfy it
the reliability and resolution numbers in every report are wrong.

**Test data.** Four forecasts (0.5, 0.9, 0.1, 0.9) against outcomes
(1, 1, 0, 0) give Brier scores 0.25, 0.01, 0.01, 0.81 by hand. Skill of a
score half the reference is 0.5. For the decomposition, 500 forecasts are
drawn uniformly and outcomes drawn from them, so the forecasts are
calibrated by construction: reliability must be small (< 0.01), the
residual (within-bin variance) non-negative, and Brier = REL − RES + UNC +
residual exactly. Four forecasts placed at bin means make the residual
exactly zero and the ECE $(2 \cdot 0.3 + 2 \cdot 0.2)/4$ by hand.

### `tests/test_sizing.py`

**What.** The fee formula, the Kelly fraction, side selection, the cap,
and the minimum-edge filter.

**Why.** The Kelly fraction is what turns a probability into money; a sign
error here loses the bankroll on correct forecasts.

**Test data.** Belief 0.6 at price 0.5 gives $f^* = 0.2$; a 0.50/0.52
quote with belief 0.6 buys yes at 0.52 with $f = 0.25 (0.6 - 0.52)/0.48$,
and belief 0.3 buys the complementary share at 0.50; a belief inside the
spread trades nothing; a 0.1 fee rate removes a one-point edge; a 5%
minimum edge removes a three-point one and keeps a six-point one.

### `tests/test_simulate.py`

**What.** Settlement order, compounding, the resting-size independent path,
and geometric decay under the cap.

**Test data.** Three opportunities listed out of settlement order; the
bets must settle by date, the second stake must be a fraction of the
bankroll left by the first, and a profit must equal shares minus stake.
Five certain losses at the 5% cap leave $10 \times 0.95^5$.

### `tests/test_backtest.py`

**What.** Market selection (label, kind, seeded sample, settlement order)
and the runner end to end on the temporary resolved set of the Phase 8
tests: the common-set rule, scores, skill, bets, and the files written.

**Test data.** Only one of six markets has a stored history, so only it has
a price at the cutoff; with the default Elo (three games required) the
common set is empty and no figures are written. With a lenient Elo the
common set is that one market, on which the market's price of 0.90
against a Yes gives Brier 0.01 and the constant 0.25, skill $1 - 25$; the
constant buys the complementary share at 0.90's ask and loses; three PNGs
and the registry appear and the summary carries the constant's row.

## Live Backtests

Histories were fetched for a seeded sample of 400 resolved 2026 markets
per domain (parsed kinds only: `daily_temperature`, EPL `match`, CS2
series `match`), at about one market per second including the hourly-then-
daily fallback. Every backtest below ran on that sample in 12 to 15 s.

### Weather, climatology against the market

`vp backtest --domain weather --forecasters market constant climatology
--kinds daily_temperature --hours-before-close H --min-edge E`:

| Cutoff | Scored | Market Brier | Climatology Brier | Skill | Climatology REL / RES | Market REL / RES |
| :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| 24 h | 348 | 0.0665 | 0.0788 | −0.19 | 0.0144 / 0.0076 | 0.0071 / 0.0117 |
| 6 h | 366 | 0.0270 | 0.0743 | −1.75 | 0.0105 / 0.0090 | 0.0083 / 0.0547 |

The constant 0.5 scores 0.25 as it must (skill −2.8 and −8.2). The market
is sharper than climatology at a day out and far sharper six hours out,
when the day's observations are mostly in; climatology's resolution barely
moves with the cutoff because its evidence does not. Bets: with no edge
threshold, climatology bet on 341 of 348 markets and lost 86% of the
bankroll to the spread; with a 5% minimum edge it placed no bet at all.
The constant baseline bets the full cap on every near-certain market and
loses everything, which is the sizing rule working as specified on a
forecaster with no information.

**Reading.** On daily temperature buckets the market's price is a better
forecast than a climatology built from the venue's own resolved buckets,
by a wide margin. This is the expected result, and the reason the plan
puts numerical-weather-prediction output on the list for weather: a
forecaster needs the forecast the market is presumably already pricing.

### EPL, Elo against the market

`vp backtest --domain epl --forecasters market constant elo --kinds match
--hours-before-close H --min-edge 0.05` on the 400-market sample (398 with
a price at the cutoff; 65 of the 400 histories are hourly, the rest daily):

| Cutoff | Scored | Market Brier | Elo Brier | Skill | Elo REL / RES | Market REL / RES |
| :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| 24 h | 389 | 0.2178 | 0.2223 | −0.021 | 0.0046 / 0.0103 | 0.0072 / 0.0149 |
| 2 h | 391 | 0.2082 | 0.2227 | −0.069 | 0.0047 / 0.0104 | 0.0041 / 0.0232 |

Elo from the venue's own resolutions is within two points of the market a
day out and is the better-calibrated of the two (reliability 0.0046
against 0.0072); it lacks the market's resolution, and the gap widens as
the market sharpens toward kick-off while Elo, whose evidence is the same
at both cutoffs, does not move. Its bets (167 at a 5% minimum edge) return
−3% at 24 h and −57% at 2 h, with a bootstrap $P(\text{Sharpe} > 0)$ of
0.59 and 0.21: no edge.

The constant baseline is the surprise of the run: +97% at 24 h from 340
bets, $P(\text{Sharpe} > 0) = 0.87$, but −9% at 2 h. A belief of 0.5 buys
the complementary share of every side priced below 0.45, which is a bet
against long shots; the favourite-longshot bias is a known feature of
sports markets and the 24-hour figure is consistent with it, but the
interval includes zero, the 2-hour figure reverses it, and a strategy
that requires the market to be biased in a fixed direction is not a
forecast. It is recorded because it is what the data said, and as the
kind of result the leakage check and forward loop exist to test.

### CS2, Elo against the market

Same command with `--domain cs2` on the 400-market sample of series
markets (80 hourly histories). CS2 markets are listed a day or two before
the match and most histories are daily bars, so only 124 of the 400 have
a price 24 hours before settlement and 291 have one two hours before;
the two rows are therefore different market sets.

| Cutoff | Scored | Market Brier | Elo Brier | Skill | Elo REL / RES | Market REL / RES |
| :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| 24 h | 107 | 0.1889 | 0.2124 | −0.12 | 0.0118 / 0.0442 | 0.0147 / 0.0684 |
| 2 h | 253 | 0.1716 | 0.2311 | −0.35 | 0.0045 / 0.0239 | 0.0058 / 0.0838 |

Elo has real resolution here (0.044 a day out, against 0.068 for the
market) and is roughly as well calibrated, but it is clearly the weaker
forecast, and its bets lose: −25% at 24 h ($P(\text{Sharpe} > 0) = 0.40$)
and −95% at 2 h, where the market has moved on information (rosters,
map picks, the first map) that a series rating cannot see. The constant
baseline loses everything in both settings, as expected in a domain
without a favourite-longshot bias to exploit.

## Summary

| Domain | Best baseline | Skill vs market (24 h) | Bets at 5% min edge | Verdict |
| :--- | :--- | ---: | :--- | :--- |
| weather | climatology | −0.19 | none | market far sharper |
| epl | elo | −0.02 | −3%, $P > 0$ 0.59 | at par a day out, no edge |
| cs2 | elo | −0.12 | −25%, $P > 0$ 0.40 | market sharper |

No baseline beats the market, which is the expected state before the LLM
forecaster and any external evidence (NWP output, rosters) are brought in,
and it is the honest bar the LLM forecaster now has to clear. The runner
itself is fast (1 to 13 s per 400-market run after the histories are on
disk) and the figures (`reliability.png`, `cumulative_score.png`,
`equity.png`) are written per run under `data/backtests/`.
