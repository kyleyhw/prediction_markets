# Portfolio, Risk and Strategy Health (Phase 20)

A paper account with thirty open positions is a portfolio, whatever its
owner calls it. Bets on binary contracts are correlated within an event,
and they settle together. This phase adds four things:

- **risk**: an exposure model with a worst case and loss quantiles;
- **sizing**: Kelly fractions chosen jointly rather than one bet at a
  time;
- **health**: whether a running strategy still beats the market, tested
  sequentially;
- **promotion**: the numbered criteria a strategy must meet before it may
  move from backtest to paper to live, with a person approving each move.

It closes flag F6, "per-market caps are not portfolio caps". Nothing here
trades: live execution is Phase 22, and this phase supplies the gate it
will use.

## Decisions, taken as proposed

| Question | Decision |
| :--- | :--- |
| Probability for risk | The market's price at the latest snapshot, not the strategy's belief. Risk should not rest on the claim being tested. Kelly uses the belief, as sizing always has. |
| Dependence within a negative-risk event | Exact: exactly one of the event's markets resolves Yes (a weather day's buckets, a match's home, draw and away). Outcomes are drawn as one categorical variable, with the prices normalised to sum to one and an "other" outcome for markets not held. |
| Dependence within any other event | A Gaussian copula with correlation 0.5 between the markets of one event (a series and its maps, a match and its totals). This is a documented simple model; the report measures how much it changes the tail. |
| Dependence between events | Independent, except that markets resolving on the same day in the same domain share a common factor with correlation 0.1 (weather across cities, one match day's results). Also documented and simple. |
| Simulation | 20,000 joint draws, seeded; the worst case is computed exactly, not sampled. |
| Loss measures | Worst case at settlement; the 95% and 99% loss quantiles; expected shortfall at 95%; concentration by event, domain and resolution date. |
| Simultaneous Kelly | Maximise expected log growth over the joint draws with the fractions non-negative and summing to at most one (full Kelly). Then, in the engine's order, scale by the fractional multiplier (a quarter) and apply the per-position cap (5%) and the per-event cap (10%). Solved by projected gradient ascent; exclusive events are enumerated exactly rather than sampled. |
| Health states | `too early` below 20 settled; then `healthy`, `watch` or `decayed`, from a one-sided CUSUM on the standardised paired advantage over the market, with the thresholds below. |
| Decay action | `decayed` pauses a paper strategy (its account stops opening positions, and settlements continue), notifies the owners and emits `strategy.health`. In live (Phase 22) the pause is mandatory. A person resumes it. |
| Promotion | Six criteria with numbers, each an evidence row linked to its run or account and each written to the audit chain. A person approves on the page. The model can never promote. Promotion to live marks the version as eligible, and nothing else, until Phase 22. |
| Combinatorial positions | The venue lists parlays and combos as ordinary binary markets and carries a `comboStatus` flag ("disabled" or "pending"). They are assessed against their legs' prices (the Fréchet bounds and the independence price), recorded, and not traded. |

## The exposure model (task 98)

A position is one side of one market held by a strategy's paper account:
its shares, its stake, and the market's event, domain, scheduled end and
negative-risk flag. At settlement a position pays its shares if its side
wins and nothing otherwise, so its P&L is payout minus stake.

A draw assigns every market an outcome. Events are simulated as follows:

- **Negative-risk events:** one categorical draw per event.
- **Other events:** a correlated normal vector through the copula, which
  is compared with each market's price.
- **The common factor:** per domain and day, added to the latent normals
  of every non-exclusive market.

The **worst case** is exact: each event's worst outcome (for an exclusive
event, the single winner that minimises the payout; otherwise every held
side losing), summed over events. Quantiles and expected shortfall come
from the draws.

Concentration is each group's share of open stake, with the largest
group named: by event, by domain, and by resolution date.

## Simultaneous Kelly (task 99)

For a set of positions open at the same time, $f$ is the vector of
fractions and $R$ is each draw's return per dollar on each position (the
payout over the price including the fee, minus one). It maximises

$$\frac{1}{N} \sum_{s=1}^{N} \log\left(1 + \sum_i f_i R_{s,i}\right)$$

under the caps, using the belief's probabilities for the draws. Per-bet
Kelly ignores the other positions. On a negative-risk event it can put
more than the whole bankroll on buckets of which at most one can win.

**The backtest comparison.** For each event with several priced markets,
the two sizings are compared on the realised outcome:

- per-bet Kelly as the engine sizes today (a quarter Kelly, 5% cap);
- simultaneous Kelly with the same multiplier and caps.

The measure is the realised log growth per event, with a paired bootstrap
interval over events.

## Risk x-ray (task 100)

A page, `#risk`, covers every paper account of the workspace:

- exposure by domain, event, resolution date and strategy;
- the worst case and the quantiles;
- "what if every favourite wins": a deterministic scenario, each
  position's side winning exactly when the market prices it above one
  half;
- the stake against the book's resting size at entry, where the order
  recorded it.

In Simple the page is one sentence and a meter: "The most you could lose
this week is $X of play money; in 19 weeks out of 20 you would lose less
than $Y." "This week" means positions whose events end in the next seven
days.

## Strategy health (task 101)

With $d_t$ the paired Brier advantage over the market on the $t$-th
settlement ($d > 0$ is better than the market), standardised by its
running standard deviation as $z_t$, the one-sided CUSUM for a downward
shift is

$$S_t = \max(0,\; S_{t-1} - z_t - k), \qquad k = 0.25,$$

which detects a drop of half a standard deviation. The state is:

- **`decayed`:** $S_t > H$, with $H = 18$. The threshold was chosen by
  simulation over 500 settlements at par, with the running standard
  deviation as in production. A strategy exactly at par is falsely
  declared decayed 0.7% of the time with normal noise and 4.9% with
  skewed noise (Brier differences are skewed). A drop of half a standard
  deviation is always detected, after a median of 62 settlements; a drop
  of a quarter is detected 77% of the time within 500. The first guess,
  $H = 8$, gave 48% false alarms at par.
- **`watch`:** $S_t > H/2$, or the latest 25 settlements' advantage
  interval lies wholly below zero.
- **`healthy`:** otherwise, once 20 settlements are in.

A state must hold for two consecutive checks before it changes, so one
settlement cannot flip it back and forth. Every transition is stored with
its time and $S_t$. The **decay report** of a strategy is its transitions,
the path of $S_t$, the rolling advantage and the settlements since the
last healthy state.

The check runs after every settlement job.

## The promotion protocol (task 102)

A strategy version moves backtest → paper → live only with every
criterion met.

| # | Criterion | Number | Evidence |
| :---: | :--- | :--- | :--- |
| 1 | Enough markets for the edge claimed | backtest scored at least the run card's `needed_n` | the run |
| 2 | Skill in the backtest | bootstrap probability of a positive advantage ≥ 0.95 | the run |
| 3 | Skill forward (for live) | the paper advantage's interval excludes zero, or at least 100 settled with a positive advantage | the paper account |
| 4 | No leakage (for live) | the leakage check's gap for the belief does not lie wholly above zero | the leakage job |
| 5 | Healthy (for live) | health `healthy` for at least 4 weeks | the health log |
| 6 | Within the mandate | worst case of the account's open positions ≤ 20% of its bankroll, and no event over 10% | the exposure model |

**Backtest to paper** needs 1 and 2. **Paper to live** needs all six.

Each evaluation writes one audit row per criterion (`promotion.criterion`,
with the evidence ids), then a `promotion.decision` row when a person
approves. Approval is a browser-session act by an owner or editor; tokens
and the model cannot approve. A strategy that fails a criterion shows
which one, by how much, and what would change it.

## Combinatorial positions (task 103)

A conjunction "A and B" priced at $c$, with legs priced $a$ and $b$,
should lie within the Fréchet bounds $\max(0, a + b - 1) \le c \le
\min(a, b)$. It is priced as independent at $ab$, and the gap $c - ab$ is
the correlation the market implies.

A price outside the bounds is an inconsistency, which only the venue's
legs and fees can say is tradeable. A conjunctive strategy (a parlay of a
strategy's own picks) and a hedge (a conjunction against its legs) are
assessed this way and written to the report. No leg linking exists in the
venue's data, so legs are matched by hand for the assessment. Nothing is
traded or offered.

## Where it lives

- **The engine** (`vp/portfolio/`): `exposure.py` (positions, the joint
  model, simulation, worst case), `kelly.py` (simultaneous Kelly and the
  backtest comparison), `health.py` (the CUSUM and states), `combos.py`
  (bounds).
- **The platform** (`vp/platform/portfolio.py`, migration 0025):
  - `strategy_health` rows and transitions;
  - the promotion evaluations and decisions;
  - the health check after settlement;
  - `/api/risk`, `/api/strategies/{id}/health` and
    `/api/strategies/{id}/promotion`;
  - the `#risk` page, and health and promotion on the strategy page.
