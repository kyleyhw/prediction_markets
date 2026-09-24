# Phase 19 Test Report: The Shadow Forecaster

Date: 2026-09-24. Environment: Python 3.14.7 via `uv 0.12.18`, Postgres 16
in the development container, the venue's public Data API, Gamma and price
history over the container's proxy. The datasets are the Phase 17 ones,
rebuilt on 2026-09-23 and holding 400 price histories per domain.
`vp serve` ran on the local stand-in, and the browser was Chromium with
axe-core. No credentials of any kind were used, and nothing was written to
the venue.

## Purpose

A person who already trades has a record, and on this venue every
address's record is public. The phase turns a pasted address into a
report card with four parts:

- what the trades imply about the person as a forecaster;
- the rule, in the strategy spec's own words, that describes when and on
  which side they bet, but only if it holds on a held-out part of the
  record;
- where the gap between them and that rule comes from;
- their standing against the venue's listed traders.

The design went into `docs/shadow.md` first; its decisions were taken as
proposed.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |
| `pytest -q` | 344 passed (337 before the phase) | 28 s |

| File | Tests | What |
| :--- | ---: | :--- |
| `test_shadow.py` | 6 | Fills aggregate into bets; splits and merges are set aside, as are sales of shares never bought. Outcomes come from settlement only, and a closed but unsettled market stays unscored. The closing line is read at the event's time, and bets outside our datasets get none. Edge, CLV, skill, calibration and habits are computed on a record built to known values. A rule is found, validated on held-out data, and round-trips through the spec. The counterfactual's parts add up to the gap exactly. Ownership recovery is checked against a published EIP-191 example and through a proxy wallet. |
| `test_platform_shadow.py` | 1 | Consent is required. The job runs on the synthetic record with the venue replaced, and keeps the raw activity in the object store. The card exports as CSV. "Try it" opens the rule as a spec that confirms as a strategy. A wrong signature fails and the right one verifies. A teammate in the same workspace cannot see the import. |
| `test_contribution_gates.py` | changed | the design page may name the reference project, as attribution |

## Reading a Record (task 92)

The venue serves an address's activity from Data API v2, 500 rows a page,
following a cursor (checked on 2026-09-24). The other public reads also
answer without credentials:

- the P&L series from `user-pnl`;
- the public profile from Gamma, which names an address's proxy wallet;
- the category leaderboards.

| Address (anonymised) | Activity read | Time | Bets | Scored | In our domains |
| :--- | ---: | ---: | ---: | ---: | ---: |
| A, first on the weather leaderboard | 20,000 (cap) | 5 min 14 s | 277 | 245 | 27 |
| B, active across 38 of 40 sampled weather markets | 20,000 (cap) | 5 min 43 s | 5,427 | 4,530 | 3,735 |

Most of the time goes on asking the venue for settlements and price
histories, at its pace. Reading the activity itself takes about 1 s a
page. A's 19,214 fills make 277 bets: the unit of analysis matters.

## Diagnostics (task 93)

The table is address B, with 95% bootstrap intervals over bets:

| Measure | Value |
| :--- | :--- |
| Return per dollar, before fees | +1.1% on 97,871 USD staked |
| Edge per bet ($y - p$) | +1.0 points [+0.3, +1.7] |
| Closing-line value | −4.6 points [−9.1, −0.4] on 117 priced bets; 41% closed above the entry |
| Skill against the close | −0.67 (Brier 0.057 at entry, 0.034 at the event) |
| Stake above 80¢ | 74%, winning 98.5% at a mean price of 96¢ |
| Stake under 20¢ | 2.4%, winning 2.5% at a mean price of 5.4¢ |
| Chasing | 31% of bets came after a five-point rise; CLV −10.4 points against −1.8 for the rest |
| Fee drag if every buy paid the taker fee | 71% of gross profit (an upper bound) |

The card's plain-language summary for B reads:

> Across 4530 settled bets you made +1.1% per dollar staked, before fees.
> The side you chose won 63% of the time, at an average price of 62%.
> After you bought, the market usually moved against you: on average the
> closing price was 4.6 points below what you paid (41% of bets closed
> higher). Your costliest habit looks like chasing: 31% of bets came after
> the price had already risen 5 points in a day, and those did worse
> against the close (-10.4 points) than the rest (-1.8).

## Rules (task 94)

For B's 3,728 weather bets, the fit used the first 2,608 and held out the
last 1,120. Negatives were 200 markets in the window priced from the venue
(each standing for 47). The three rules the search found were all
rejected on the held-out part:

- The best covered 12% of held-out bets, where 25% is required.
- The rules agreed on the side about half the time, where 80% is
  required.
- Their lift was 2.6, where 3 is required.

B bets across thousands of temperature markets at every price, and no
single rule in the spec's vocabulary describes that. The card says so
rather than offering a rule.

On the synthetic record, a person who always bought the favourite at 70¢
a day out, the rule was found and validated: coverage 100%, agreement 100%,
lift 6.3. The rule read "Buys the favourite in match markets when it is
priced 55% to 70%, about 24 hours before the close". "Try it" opened it
as a spec, and it confirmed as a strategy in the browser.

The model's proposals are built but not run, because they need a key. The
card says the rules were found by search only.

## Counterfactual (task 95)

Only a validated rule gets a counterfactual, so none of the real records
has one. On the synthetic record the person made −7.2% per dollar and the
rule −2.0%, on the 70 markets it would have picked. The three parts add
up to the gap exactly (tested). The timing part is non-zero only through
the one early sale, since exits count as timing.

## Report Card and Peer Context (task 96)

Peer context comes from the venue's leaderboard for the record's main
category. It is anonymised to a percentile, with three caveats on the
card: the list is top addresses only, its profit is gross of fees, and its
volume includes market making.

| Address | Category | Percentile of profit per dollar among 50 listed |
| :--- | :--- | ---: |
| A | WEATHER | 74th |
| B | WEATHER | 18th |

The browser walk-through covered:

- the empty page;
- the consent refusal: "Tick the box to agree to linking the address
  first";
- the queued state, the list, and both cards in Simple and Detailed, one
  in dark;
- the JSON export and "Try it" through to a confirmed strategy.

axe-core at WCAG 2.2 AA found **zero violations on 9 page states**.

## A Signal From Skilled Addresses? (task 97)

**Setup.** From 150 weather markets with histories, all the venue's public
trades were read (it serves about 3,000 per market). That gave 13,373 bets
by 7,208 addresses. In 93% of markets the trades reached back past the
cutoff 24 hours before the event.

**Formation.** Of the 120 addresses with five or more bets on markets
before the median date, the 20 with the highest positive mean CLV were
chosen.

**Evaluation.** Only later markets were used:

| Group | Bets | CLV, points | Edge ($y - p$), points |
| :--- | ---: | :--- | :--- |
| The 20 chosen | 97 | +1.0 [−1.8, +3.9] | +4.8 [−0.7, +9.8] |
| Everyone else | 3,971 | −1.4 [−2.0, −0.8] | −0.2 [−1.3, +0.8] |

**As a point-in-time signal.** Following the chosen addresses' net dollars
from trades before the cutoff, at the market's price at the cutoff, gave
a bet on 20 markets. It returned **+9.7% per dollar [−15%, +34%]**.

**Verdict: not worth building now.** Past CLV carried over in direction,
since the chosen addresses were better than everyone else afterwards. The
intervals include zero, and the signal fires too rarely to bench: 20
markets, when Phase 16's gates need hundreds. Two things would change
that:

- trades captured forward into the evidence archive, so the formation
  window can be long without the venue's depth cap;
- a larger sample of markets.

It stays a hypothesis in `docs/shadow.md`.

## Found and Fixed

| Fault | Fix |
| :--- | :--- |
| The closing price was read at the market's closing time. Trading runs past the event, so that price is the result: skill against the close came out as −16.6 on the first real card. | The line is read at the event's scheduled time (`end_date`). Bets without one (outside our datasets) get no line. |
| Rules had no negatives when the dataset's local histories did not overlap the person's active window: B's window was the last fortnight, and the histories stop at 2026-09-12. Every rule scored a lift of 1 and could never validate. | Up to 200 window markets are priced from the venue on demand. |
| `fetch_activity(max_items=1200)` returned 1,500: the API ignores a smaller last-page limit. | The generator stops at the cap itself. |
| The band search took the `argmax` of an empty list at the top of the grid. | Skipped. |
| `coincurve` has no wheel for Python 3.14 and does not build. | `eth-keys` with a pure-Python backend, plus `eth-hash` (keccak) over `pycryptodome`. Recovery matches a published EIP-191 example. |

## Not Done

- Model-proposed rules need a key, like task 60. The path is built and
  validated the same way; it has not run.
- Addresses are read up to 50,000 activities. The oldest part of a very
  active record is cut, and the card says so.
- The skilled-address signal is not added to the library (task 97).
