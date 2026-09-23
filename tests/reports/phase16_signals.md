# Phase 16 Test Report: Signals, Blends, Committees and the Benchmark

Date: 2026-09-23. Environment: Python 3.14.7 via `uv 0.12.18`, Postgres 16
in the development container, Chromium through Playwright with axe-core;
`vp serve` and one worker over a local store holding the demo datasets
built from the live venue that day; for the bench, the full resolved sets
built from the venue on 2026-09-13 (88,668 CS2, 12,716 Premier League,
134,077 weather markets) with 400 price histories per domain.

## Purpose

The plan's Phase 16 asks for tested, cutoff-safe signals with a one-line
bench against the market, blends and committees as beliefs a strategy can
name, contamination accounting, a public benchmark that commits forecasts
before its questions resolve, and a checklist for new signals. The design
page came first (`docs/signals.md`); the phase's decisions were taken as
proposed.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |
| `pytest -q` | 308 passed (285 before the phase) | 25.6 s |

| File | Tests | What |
| :--- | ---: | :--- |
| `test_signals.py` | 21 | every one of the eleven signals passes purity, metadata and the cutoff sentinel (11); the gates catch an impure module (an `os` import, `open`, the clock, missing metadata) and a leaky one; the new evidence accessors stop at the cutoff; the goals grid prices home, draw and away to one; a signal is a belief a spec can name and render; the bench pairs signals with the market and classifies them; a blend declines without enough history and ignores later rows; the aggregation rules; a committee asks each role and combines them by its rule; a model with no recorded cutoff counts as contaminated; the benchmark freezes reproducibly, detects a tampered payload and scores |
| `test_platform_signals.py` | 2 | the bench job keeps the latest result per domain; a week is frozen and sealed, shows only commitments, refuses an edit (the trigger), waits for settlement, then reveals, verifies and scores |
| `test_ui_catalogue.py` | +0 | now also covers the Signals page's keys, its verdicts and the new job kinds |

The cutoff sentinel is the slow part: the two calibration signals refit
on each of the fixture's 250 weather days, 4.3 s each.

## The Gates and the Checklist (tasks 63, 70)

`vp signals check --root <root>` runs the checklist on every signal:
purity (an AST scan of the module), metadata (id, title, cutoff
semantics, warm-up, licence note, a reference, the accessors read), the
cutoff sentinel (fixtures with and without rows after 2026-03-01; every
value must be the same, and a later cutoff must never change an earlier
value) and a bench on at least one domain. On the full-data benches all
eleven signals pass, in 9.9 s. Without a bench, the check fails and says
"no bench on any domain".

## The Library (task 64)

| Signal | Domains | Source |
| :--- | :--- | :--- |
| Elo, Glicko-2, Bradley-Terry | every match domain | Elo 1978; Hvattum and Arntzen 2010; Glickman 2012; Bradley and Terry 1952, fitted as Hunter 2004 |
| Map Elo | CS2 maps | Elo, per map |
| Poisson, Dixon-Coles | football results and totals | Maher 1982; Dixon and Coles 1997 |
| Climatology, persistence | weather buckets | Wilks 2011, ch. 7 |
| Bucket normalised | weather buckets | the event's own prices summing to one |
| Platt, isotonic | every domain | the market's price recalibrated on earlier settled markets: Platt 1999; Zadrozny and Elkan 2002; the favourite-longshot bias, Snowberg and Wolfers 2010 |

Not yet built from the plan's list: pi-ratings, rest days and congestion,
roster flags, the microstructure signals (spread, depth, drift, volume,
holders) and the forecast-ensemble signal, which needs the Phase 17
archive.

## The Bench (task 65)

`vp signals bench --domain <d> --hours 24 --max-markets 2000 --seed 0`,
each signal against the market's own price 24 hours before settlement on
the same markets. The advantage is the market's Brier score minus the
signal's (positive is better than the market), with a paired bootstrap
95% interval; "needs" is how many markets an advantage of that size would
need to be told from zero. Only markets with a stored price history are
drawn. Runtimes: EPL 2.4 s, CS2 12.3 s, weather 13.0 s.

**Premier League** (400 markets, 398 with a price):

| Signal | n | Brier | Market | Advantage [95%] | Verdict | Needs |
| :--- | ---: | ---: | ---: | :--- | :--- | ---: |
| Elo | 389 | 0.2223 | 0.2178 | −0.0046 [−0.0124, +0.0035] | par | 2,562 |
| Glicko-2 | 389 | 0.2257 | 0.2178 | −0.0080 [−0.0176, +0.0017] | par | 1,223 |
| Bradley-Terry | 389 | 0.2263 | 0.2178 | −0.0085 [−0.0187, +0.0018] | par | 1,230 |
| Poisson | 151 | 0.2354 | 0.2271 | −0.0083 [−0.0344, +0.0165] | par | 3,100 |
| Dixon-Coles | 151 | 0.2321 | 0.2271 | −0.0051 [−0.0292, +0.0189] | par | 7,460 |
| Platt | 193 | 0.2118 | 0.2135 | +0.0017 [−0.0045, +0.0075] | par | 5,013 |
| Isotonic | 193 | 0.2224 | 0.2135 | −0.0089 [−0.0207, +0.0019] | par | 614 |
| Blend: Elo + Platt | 77 | 0.2280 | 0.2324 | +0.0044 [−0.0071, +0.0163] | par | 1,109 |
| Blend: Bradley-Terry | 278 | 0.2172 | 0.2176 | +0.0004 [−0.0058, +0.0069] | par | 109,047 |

**Counter-Strike 2** (400 markets, 124 with a price 24 hours before
settlement; many CS2 markets open only hours before the match):

| Signal | n | Brier | Market | Advantage [95%] | Verdict | Needs |
| :--- | ---: | ---: | ---: | :--- | :--- | ---: |
| Elo | 107 | 0.2124 | 0.1889 | −0.0235 [−0.0473, +0.0008] | par | 236 |
| Glicko-2 | 107 | 0.2032 | 0.1889 | −0.0143 [−0.0480, +0.0189] | par | 1,169 |
| Bradley-Terry | 107 | 0.1998 | 0.1889 | −0.0108 [−0.0411, +0.0174] | par | 1,662 |

Map Elo and the calibrations answered none: the sample held no priced map
market, and fewer than the 200 earlier settled prices a calibration fits on.

**Weather** (400 markets, 359 with a price):

| Signal | n | Brier | Market | Advantage [95%] | Verdict | Needs |
| :--- | ---: | ---: | ---: | :--- | :--- | ---: |
| Climatology | 348 | 0.0788 | 0.0665 | −0.0124 [−0.0265, +0.0002] | par | 852 |
| Persistence | 328 | 0.0800 | 0.0643 | −0.0157 [−0.0318, −0.0007] | **anti** | 629 |
| Platt | 158 | 0.0775 | 0.0827 | +0.0052 [−0.0016, +0.0117] | par | 532 |
| Isotonic | 158 | 0.0838 | 0.0827 | −0.0011 [−0.0140, +0.0098] | par | 36,909 |
| Blend: climatology | 246 | 0.0683 | 0.0732 | +0.0049 [−0.0025, +0.0115] | par | 1,073 |
| Blend: climatology + persistence | 226 | 0.0667 | 0.0707 | +0.0040 [−0.0034, +0.0110] | par | 1,607 |

Bucket normalised had no markets in the sample whose whole event was
priced at the cutoff.

**What it says.** Nothing is alive: no signal or blend beats the market
with an interval above zero on any domain, and persistence is reliably
worse than the market on weather. The rating models match the Phase 9
Elo baselines (EPL −0.02 and CS2 −0.12 skill). The only positive means
are the market's own recalibration (Platt, +0.0017 and +0.0052) and the
blends, which start from the market's price; told from zero, they would
need from 532 to over 100,000 markets, more than the sample holds.

**Decay.** The quarterly advantages move in both directions with no
trend the samples can resolve: EPL Elo −0.011, +0.006, −0.002 over 2026
Q1 to Q3 (211, 122, 56 markets); weather climatology −0.060, −0.011,
−0.005 (32, 128, 188), shrinking towards par as the weather markets
multiplied; the weather climatology blend −0.005 then +0.008.

## Blends (task 66)

Walk-forward logistic regression of the outcome on the market's log-odds
and each signal's, fitted only on markets settled before the cutoff, with
a ridge pulling toward the market (weight one on its log-odds, zero on
the rest). Below 100 earlier settled markets a blend declines to answer;
just above that it stays close to the market's price. Every blend
benched is at par.

## Committees (task 67)

Built: three roles in `committees/standard.yaml` (base-rate analyst,
evidence analyst, red team), each seeing only the evidence and the domain
pack, combined by a rule written as data (mean of log-odds, trimmed mean,
extremising with a factor, capping), with per-role cost and rationale.
Tested against a scripted model only. **Not evaluated**: the container
holds no API key (as for task 60), so the comparison with single
elicitation and with the best blend has not run, and no committee is
offered as a default.

## Contamination (task 68)

`TRAINING_CUTOFFS` in `vp/forecast/llm.py` records each model's training
cutoff; run cards and benches split at it and count only the later
markets as skill. No cutoff is recorded yet, because none has been read
from the provider's published model information in this session, so every
model-backed result is marked contaminated over its whole window.

## The Benchmark (task 69)

Week 2026-W39 was frozen on the stand-in at 19:47 UTC on 2026-09-23,
seed 2127448886 (from the week's name), hash `981974e9…6592f`: 50
questions, two sealed configurations (the market and bucket normalised).
A committed payload cannot be changed (the trigger refused an edit in the
test), and `/api/benchmark` shows only the commitments. It is not scored:
its questions end on 24 and 25 September.

Two things narrowed that week, both about the stand-in's data, not the
code:

- All 50 questions are weather. The stand-in's newest CS2 and EPL
  captures (120 and 973 markets, taken in the morning) held no open market
  ending in the next 30 days after the freeze, so the round-robin draw
  had only weather to take from.
- Climatology, persistence and the calibrations answered nothing: the
  stand-in's store holds the demo datasets (400 weather markets, no
  weather histories). Against the full resolved set, persistence and both
  calibrations answer all 50; climatology still answers none, because
  that set was built on 2026-09-13, so the 14 days before the freeze hold
  too few observations, and "lowest temperature" questions only began in
  April 2026, so there is no earlier September. On the deployed platform
  the dataset is rebuilt daily and neither applies.

## In the Browser

The Signals page (`#signals`) under `vp serve`, with the full-data benches
loaded into the stand-in: 3 renders (Simple, Detailed, dark), axe-core's
WCAG 2.0 to 2.2 A and AA rules: no violations once a fault was fixed (see
below). The wide bench table scrolls inside its frame and takes focus.

## Found and Fixed

- The sentinel fixture indexed months out of range and held too few
  weather days for the calibrations' 200-market minimum; it now has 250
  days and is built once per test module.
- The bench drew markets without a price history and then counted them
  as unpriced; it now draws only from markets with a history.
- axe found a scrollable table the keyboard could not reach
  (scrollable-region-focusable); any overflowing frame is now focusable
  and named after its table.
- The page listed domains with no bench; they are hidden.
- A test expected an extremised aggregate above the default cap; the cap
  is part of the rule, and the test now says so.

## Not Done

- The committee evaluation (task 67) and every model-backed number: wait
  on an API key, with task 60.
- Scoring the first benchmark week: waits for its questions to resolve;
  the `benchmark_score` job runs daily.
- The rest of the library listed under task 64.
- Blends and opted-in strategies in the benchmark: blends need a fit on
  the platform's own history first; strategies need Phase 18's opt-in.
- Recording model training cutoffs from the provider's published
  information.
