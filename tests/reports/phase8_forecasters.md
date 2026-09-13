# Phase 8 Test Report: Forecasters

Date: 2026-09-13. Environment: Python 3.14.7 via `uv 0.12.13` (the container's
`uv 0.8.17` and Python 3.14.0rc2 could not import the Anthropic SDK, whose
pydantic dependency needs the final 3.14; the SessionStart hook now refreshes
`uv` so the pinned interpreter installs), Linux container with access to
Polymarket. Total runtime of the checks below: about 25 s wall.

## Purpose

Phase 8 added the forecaster contract, the cutoff-bounded evidence object,
the baselines (market price, constant, climatology), the Elo forecaster, the
LLM forecaster and the registry. The checks verify the one property every
later result depends on, that no forecaster can read past its cutoff, and
that each forecaster's arithmetic matches a hand calculation.

## Static Checks

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .` and `ruff format --check .` | passed | < 1 s |
| `ty check` (`error-on-warning`) | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 5 s |

## Unit Tests

`uv run pytest -q`: 56 passed in 0.5 s (about 6 s wall including the first
Parquet import). The Phase 6 and 7 tests are unchanged; the new files:

### `tests/test_forecast.py`

**What.** Time parsing, the cutoff rule of every evidence accessor, the
market-price and constant baselines, Elo fitting and its draw handling,
climatology from realised buckets, and the registry round trip.

**Why.** The evidence object is the look-ahead safeguard; if it leaks, every
backtest score is optimistic. The forecasters' formulas are the rest.

**Test data.** A resolved set written to a temporary data root with the
same writer the dataset uses: six EPL side markets in two rounds settling
on 2026-03-01 and 2026-03-08, and a cutoff of 2026-03-05 between them, so
every accessor is checked to return round one and not round two. A price
history with points before, at and after the cutoff checks that the point
stamped exactly at the cutoff is served and the next is not. Elo on the
two round-one results gives ratings 1516 and 1484 by hand, and the forecast
for the round-two market is checked against the closed form including the
draw correction. Seven weather markets give five realised London highs in
2025 plus one after the cutoff; the climatology for a 2026 bucket is
$(3 + 1)/(5 + 2)$ by hand. A naive cutoff (no timezone) is rejected.

### `tests/test_llm.py`

**What.** The elicitation loop against a fake client that plays the model:
it calls two evidence tools, then answers in the structured JSON shape.

**Why.** The loop cannot be run against the API here (no credentials in the
container), so the request shape, tool routing, cost arithmetic and sample
averaging are pinned offline; the live run is a matter of setting a key.

**Test data.** The same EPL set. The fake asserts that the tool results it
receives contain round one and not round two, so the tools are shown to go
through the cutoff-bounded evidence. Two samples answering 0.6 and 0.7
average to 0.65; four calls of 1,000 input and 100 output tokens cost
$4 \times (1000 \times 5 + 100 \times 25)/10^6 = \$0.03$ at the Opus 5
prices. The user turn is checked not to contain the market price. A client
that raises makes the forecaster decline rather than fail the run.

## Live Checks

Evidence built from the full resolved sets of 2026-09-13 with a cutoff of
2026-09-01 (16 s to load all three domains):

| Domain | Results before cutoff | Draw rate | Teams | Top ratings |
| :--- | ---: | ---: | ---: | :--- |
| epl | 809 (2024-04-11 to 2026-08-31) | 0.26 | 126 before canonicalisation | Arsenal 1694, Aston Villa 1680, Manchester City 1673 |
| cs2 | 10,257 (2024-09-20 to 2026-08-31) | 0.00 | 1,316 | Spirit 1915, Vitality 1847, Team Falcons 1799, MOUZ 1794 |

The EPL draw rate matches the league's long-run figure, and the top of both
tables is the teams that won the 2025-26 titles and the 2026 CS2 majors,
which is the sanity check a rating from results alone can pass. The team
count exposed that 2024 fixtures name `Arsenal` and 2026 ones `Arsenal FC`;
names are now canonicalised (suffix dropped, case folded) before rating.

Realised daily highs served as climatology evidence: London 569
observations (2025-01-22 to 2026-08-31), Seoul 237, Cape Town 143, each at
one-degree resolution in the 2026 markets.

**Not run.** The LLM forecaster against the API: the container holds no
Anthropic credentials. `LLMForecaster()` constructs a client from the
environment, so the first keyed run needs nothing but the key.
