# Phase 20 Test Report: Portfolio, Risk and Strategy Health

Date: 2026-09-24. Environment: Python 3.14.7 via `uv 0.12.18`, Postgres 16
in the development container, `vp serve` on the local stand-in, and
Chromium with axe-core. Two further sources were used:

- the Phase 13 stand-in's own Postgres volume, brought up read-only for
  its paper record;
- the Phase 17 datasets, with event price histories fetched from the
  venue where the dataset held only a sample.

Nothing here trades.

## Purpose

A paper account's positions are one portfolio, since bets within an
event are correlated and settle together. The phase adds five things:

- an exposure model, with a worst case and loss quantiles;
- Kelly fractions sized jointly;
- a health check that pauses a strategy that has stopped beating the
  market;
- numbered promotion criteria that a person approves;
- an assessment of conjunctions against their legs.

It closes flag F6 ("per-market caps are not portfolio caps"). The design
went into `docs/portfolio.md` first, and its decisions were taken as
proposed.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |
| `pytest -q` | 350 passed (344 before the phase) | 31 s |

| File | Tests | What |
| :--- | ---: | :--- |
| `test_portfolio.py` | 5 | The worst case is exact, with exclusive markets never both winning in the draws and a hedge worth nothing at worst. The "every favourite wins" scenario. Simultaneous Kelly matches the closed form on one bet and respects the caps on three exclusive buckets. Health goes from too early to healthy, and detects a decline; a flat advantage stays finite. A conjunction is checked against its legs. |
| `test_platform_portfolio.py` | 1 | The x-ray of two exclusive positions (worst case −70, not −70 twice). Sixty poor settlements: decayed, paused, owners notified, resumed by a person. Promotion to paper is advisory (two criteria); to live, six criteria are evaluated with six audit rows. A failing evaluation cannot be approved, a token cannot approve, and a person can. |

## The Exposure Model and Its Tail (task 98)

The tail depends on the dependence model, and the report was to measure
by how much. The test book held 20 events of three correlated favourites
and 10 exclusive events with two buckets held each, over five days: 80
positions, 1,600 USD staked. The worst case is exact: −1,600.

| Within an event | Across a day | Loss not exceeded 19 in 20 | 99 in 100 |
| ---: | ---: | ---: | ---: |
| 0 | 0 | 221 | 315 |
| 0.5 | 0 | 268 | 375 |
| **0.5** | **0.1** | **311** | **437** |
| 0.5 | 0.3 | 386 | 549 |
| 0.9 | 0.1 | 352 | 508 |

The default (bold) sits in the middle. Treating everything as independent
understates the 1-in-100 loss by 28%, and a stronger day factor raises it
by 26%. The page states the model it used and never shows a single tail
number without it.

## Simultaneous Against Per-Bet Kelly (task 99)

Events were taken from the datasets with every market priced 24 hours
before settlement. The histories came from the venue: 440 weather, 444
Premier League and 149 CS2 markets. Each market was sized both ways at the
backtest's quote (the price plus or minus a cent) and its own fee, then
scored on the realised outcome. The measure is log growth per event.

| Domain | Belief | Events compared | Per-bet stake per event (mean, max) | Per-bet | Per-bet, event cap only | Joint | Joint − per-bet |
| :--- | :--- | ---: | :--- | ---: | ---: | ---: | :--- |
| weather (exclusive buckets) | `signal:nwp_forecast` | 30 (217 positions) | 22.8%, 49.3% | −4.4% | −1.9% | −2.2% | **+2.2 [+0.1, +4.0] points** |
| Premier League | `elo` | 5 | 4.6%, 7.1% | −0.03% | −0.03% | −0.5% | −0.5 [−2.4, +1.5] |
| CS2 (series and maps) | `elo` | 6 | 7.6%, 15.0% | +3.2% | +3.0% | +2.2% | −1.0 [−3.4, +0.8] |

On weather, per-bet Kelly staked nearly half the bankroll on one day's
buckets, of which at most one can win. Joint sizing did better beyond
noise, and the gain is **the event cap's**: joint minus capped per-bet is
−0.3 [−1.1, +0.6] points. The optimisation adds nothing measurable once
the cap is there. On the other domains too few events had every market
priced and a belief (Elo needs both teams' records) to tell anything.

The per-event cap is the part that matters, whichever way positions are
sized. Positions of every sizing are still judged by the backtest
against the market, and no belief here has beaten it.

## Risk X-Ray (task 100)

The browser walk-through gave a new account four open positions: two
results of one match (exclusive), one of another match, and one
non-exclusive market. The page said: "The most you could lose this week
is $80.00 of play money; in 19 weeks out of 20 you would lose less than
$80.00." Across all four the worst case is −160, and if every favourite
won the account would make +$66.13. The Detailed tables showed:

- concentration by domain, event (the match with two positions held 50%),
  date and strategy;
- the model's parameters.

## Strategy Health on the Paper Record (task 101)

The threshold $H = 8$, the first guess, was set aside after simulation:

| $H$ | At par, normal noise: false decay within 500 | Skewed noise | Half-SD decline: detected (median settlements) | Quarter-SD decline |
| ---: | ---: | ---: | :--- | ---: |
| 8 | 48% | 30% | 100% (24) | — |
| 14 | 3.1% | 7.9% | 100% (43) | — |
| **18** | **0.7%** | **4.9%** | **100% (62)** | **77%** |
| 20 | 0.4% | 3.5% | 100% (68) | 66% |

The stand-in's own paper record (the sample strategies, 2026-09-23) gave
these transitions:

| Forecaster | Settled | Mean advantage | Transitions |
| :--- | ---: | ---: | :--- |
| `constant` (0.5 on everything) | 12,483 | −0.250 | too early → decayed at 20 |
| `climatology` | 68 | −0.368 | too early → watch at 20 → decayed at 42 |

Both are correct: neither sample strategy beats the market, and the check
says so within 20 and 42 settlements. The first run exposed a fault. The
constant forecaster's advantage barely varies (SD 0.008), and dividing by
it drove the CUSUM to $1.2 \times 10^{10}$. The deviation is now floored
at 0.01.

In the browser a strategy with 80 poor settlements was found decayed,
paused ("opens no new positions, and the ones open still settle"),
notified, and resumed by a person.

## The Promotion Protocol on Every Strategy (task 102)

All six strategies on the development stand-in were evaluated for live.
None passes, and each says why:

| Strategy | Status | 1 markets | 2 skill | 3 forward | 4 leakage | 5 healthy | 6 mandate |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Counter-Strike favourites | paper | no: a follow rule makes no forecast | no | no: 0 settled | no check | not checked | yes |
| Premier League favourites (×2) | paper | no: a follow rule makes no forecast | no | no: 0 settled | no check | not checked | yes |
| Counter-Strike favourites (×2) | previewed | no backtest yet | no | no | no | no | no paper account yet |
| Rule version of 0xababab | previewed | no backtest yet | no | no | no | no | no paper account yet |

A follow rule claims no forecasting edge, so the protocol cannot promote
it on skill, and it says exactly that. The walk-through's strategy failed
five of six: forward advantage −0.140 [−0.146, −0.134], and decayed. It
met the mandate: worst case 160 of an 840 balance, largest event 80.
"Approve" appears only on a passing evaluation. The API refuses tokens,
and the model has no route to it.

## Combinatorial Positions (task 103)

The venue lists parlays and combos as ordinary binary markets. Its
markets carry a `comboStatus` flag: of 100 open markets sampled, 98 were
`disabled` and 2 `pending`. No field links a parlay to its legs.

"UFC Fight Night Parlay: Buckley and Namajunas" was matched to its two
fights by hand:

| Time | Parlay | Buckley | Namajunas | Fréchet bounds | Independent | Implied dependence |
| :--- | ---: | ---: | ---: | :--- | ---: | ---: |
| 2025-06-13 | 0.485 | 0.710 | 0.685 | [0.395, 0.685] | 0.486 | −0.001 |
| 2025-06-14 | 0.490 | 0.715 | 0.680 | [0.395, 0.680] | 0.486 | +0.004 |
| 2025-06-14 18:00 | 0.475 | 0.705 | 0.665 | [0.370, 0.665] | 0.469 | +0.006 |

The venue priced the parlay as two unrelated fights, within a point of
independence and inside the bounds. There was nothing to hedge or
exploit. (Buckley lost, so the parlay resolved No.) Conjunctions are
recorded as assessable, not traded, and a conjunctive strategy would be
priced the same way.

## Accessibility

axe-core at WCAG 2.2 AA found **zero violations on 7 page states**:

- the risk page empty, in Simple, in Detailed and in dark;
- the strategy page decayed, after the live check, and in Simple and
  dark.

The risk meter is a `meter` with its value and a label.

## Found and Fixed

| Fault | Fix |
| :--- | :--- |
| $H = 8$ declared 48% of strategies at par decayed within 500 settlements | $H = 18$, chosen by simulation |
| A near-constant advantage drove the CUSUM to $1.2 \times 10^{10}$ (the constant forecaster on the stand-in) | the running deviation is floored at 0.01 |
| A strategy found decayed on its first check told nobody, because notices required an earlier state other than "too early" | notices on any move into watch or decayed, and on recovery |
| Criterion 6 compared against a bankroll of 0 for an account that had traded nothing | the account's starting cash |
| Criteria 1 and 2 said "needed None" for a follow rule | "a follow rule makes no forecast, so it claims no skill to test" |
| The worst case printed as "-0.00" | never negative zero |
| Paper orders did not record what the exposure model needs | orders now carry the market's end date, negative-risk flag and the resting size at entry |

## Not Done

- Simultaneous Kelly is measured, not switched on. The event cap is what
  helped. It is checked at promotion (criterion 6), and a strategy can
  already cap positions per event (`max_per_event`); a dollar cap per
  event in paper sizing waits for a belief worth sizing.
- Health was measured on the sample strategies' record. No user strategy
  on the stand-in has settled paper positions yet.
- No strategy is eligible for live. Phase 22 reads the approvals this
  phase records.
