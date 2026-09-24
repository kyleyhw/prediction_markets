# The Shadow Forecaster: Learning From Your Own Record (Phase 19)

A person who already trades on the venue has a record. Every address's
trades, positions and P&L are public on the venue's Data API, so no broker
export or credentials are needed. A person pastes an address, and the
platform does four things:

1. It reads what the trades imply about the person as a forecaster
   (diagnostics).
2. It finds the rules, in the strategy spec's own vocabulary, that describe
   when and which side they bet (rule extraction).
3. It backtests that "rule version of you" and says where the gap between
   it and the real record comes from (counterfactual).
4. It puts all of this on one report card.

The idea is Vibe-Trading's Shadow Account (`docs/vibe_trading.md`),
rebuilt here for a venue whose records are public.

## Decisions, taken as proposed

| Question | Decision |
| :--- | :--- |
| Whose record | Any address the person pastes. The record is public, and linking it to an account is the person's own act: they tick a consent that says so. The consent's text version and time are stored with the import, and the person can delete the import at any time. |
| Proof of ownership | Optional: the person signs a one-time message with their wallet (EIP-191 `personal_sign`). The platform recovers the signer. Ownership is proven if the signer is the address, or the venue's public profile names the address as the signer's proxy wallet. Nothing is sent to the chain, and no key ever reaches the platform. Proof puts "owner verified" on the card and changes nothing else. |
| What is read | Data API v2 `activity` (trades, redemptions, merges, splits, conversions, rewards) and the venue's own daily P&L series from `user-pnl`, which is shown beside the card's figures as the venue's account (it includes fees and open positions); paged by cursor, at most 50,000 activities (100 pages; about 50 s for a very active trader). The raw pages are kept in the object store as the import's evidence. |
| Unit of analysis | A **bet**: one outcome of one market, with all its buys aggregated (VWAP entry, total stake, first entry time); sells reduce it. A trader with 19,214 fills over 327 markets has about 330 bets, not 19,214 forecasts. |
| Outcomes | From settlement evidence only: the venue's resolution record (`fetch_resolution`, the CLOB `winner` flags or the oracle's answer) or our own dataset's label. A closed market without one is not scored. Invariant: closed is not resolved. |
| Closing price | The last price at or before the market's close, from the venue's price history for the bet's token. Histories are fetched for the newest 300 resolved bets at most (about 5 minutes at the venue's pace); the diagnostics say how many had one. |
| Domains | A market belongs to a domain when our dataset for that domain holds its condition. Everything else is "other" and still counts in the diagnostics. Rules and counterfactuals need parsed fields, so they cover domain bets only. |
| Fees | The activity carries no fee. Fee drag is estimated from each market's `feeSchedule` as if every buy paid the taker fee: an upper bound, labelled as one. |

## Diagnostics (task 93)

The first outcome of the bet is the outcome the person **bought**, so every
quantity below is about the side they chose. With $p$ the entry price, $c$
the closing price and $y \in \{0, 1\}$ whether the side won:

| Measure | Definition | Reading |
| :--- | :--- | :--- |
| Return | $\sum (\text{payout} + \text{sells} - \text{cost}) / \sum \text{cost}$ | what the record made per dollar staked |
| Edge per bet | mean of $y - p$ (unweighted) with a bootstrap interval | did the chosen side win more often than its price said? |
| Implied belief | $p$ is the least probability at which buying makes sense, so it is a lower bound on the person's belief | the record reveals choices, not probabilities |
| Brier and log loss | of $p$ against $y$, beside the same for $c$ | how the prices they took compare with the closing prices |
| Skill against the close | $1 - \sum (p-y)^2 / \sum (c-y)^2$, paired bootstrap interval | negative in almost every record, since the close knows more; less negative means they entered when prices were already good |
| Closing-line value (CLV) | mean of $c - p$, the share of bets with $c > p$, and an interval | the market later agreeing with them; less noisy than outcomes, the standard measure of a sharp bettor |
| Calibration | win rate against mean entry price in bands 0–0.1, …, 0.9–1 | where they are over- or under-confident |
| Favourite–longshot exposure | share of stake at entry below 0.2 and above 0.8, and the win rate against price in each | longshots are overpriced on most venues |
| Holding period | median time from first buy to last sell or to the close | |
| Over-trading | fills per bet, the share of bets sold before the close, and the return of bets sold early against bets held | |
| Chasing | $p$ minus the price 24 hours before the first buy; the share of bets bought after a rise of 5 points or more, and their CLV against the rest | |
| Sizing consistency | coefficient of variation of stakes; rank correlation of stake with CLV; the share of stake in the largest tenth of bets | a disciplined bettor stakes more where the edge is larger |
| Fee drag | estimated taker fees over gross profit | an upper bound |

Each measure is given overall, by domain and by month, and is shown only
with at least 10 bets behind it. Intervals are 95% bootstrap intervals
over bets (2,000 resamples, seeded).

## Rule extraction (task 94)

Candidate rules are exactly what the strategy spec can express: a domain,
a kind (the parser's `kind`), a side (the favourite or the underdog of the
market's first two outcomes), an entry price band (`rule.price_min` and
`price_max`, on a grid of 0.05), a time before close
(`schedule.hours_before_close`, from 1, 3, 6, 12, 24, 48, 72, 168 hours),
and optionally one parsed-field condition (`selector.where`, with values
the person bet at least five times). Every validated rule is therefore
already a spec, and the strategy pages confirm, preview, backtest and
paper trade it as any other.

The positives are the person's domain bets. The negatives are the markets
of the same domain and kind in our dataset that closed while the person was
active and that they did not bet, priced at the rule's time before close
from their histories. Fitting is a greedy decision list:

- Pick the rule with the best F1 of recall (the person's bets it covers,
  side included) and precision (the share of markets it selects that the
  person bet).
- Remove the bets it covers, and repeat up to three rules.
- Fitting uses the first 70% of the record by time; the last 30% is held
  out.

A rule is **validated** only if, on the held-out 30%:

- it covers at least 25% of the person's domain bets;
- it agrees on the side in at least 80% of the bets it covers;
- the markets it selects were bet at least three times as often as the
  base rate;
- at least 10 held-out bets fall under it.

With a key, the model reads the diagnostics and proposes rules in words,
which the compiler turns into the same candidates. The model's candidates
are validated exactly like the enumerated ones, and are only candidates:
the model's words never become a rule. Without a key, only enumeration
runs, and the card says so.

## Counterfactual (task 95)

For the best validated rule, three things are computed on the person's
domain bets, each as return per dollar staked and **before fees**, because
the record's own returns are before fees (the activity carries none):

1. **the person as traded**: their stakes, prices and exits;
2. **the rule version of them**: the rule's own selection over the
   domain's priced markets (the dataset's histories and the person's
   bets), bought at its scheduled time and held to settlement;
3. **the market-following baseline**: taking the market's price as the
   forecast, which gives zero expected return before fees.

The rule is scored directly rather than through the strategy backtest, so
the three can be compared on the same terms. Once confirmed, the strategy's
own backtest charges fees as usual.

The gap between the person and the rule splits exactly into three parts.
Write $R_w$ for their stake-weighted return, $R_e$ for the same bets
equally weighted, $R_t$ for the same bets equally weighted at the rule's
scheduled price, and $R_r$ for the rule's equally weighted return on its
own selection. Then

$$R_w - R_r = \underbrace{(R_w - R_e)}_{\text{sizing}} +
\underbrace{(R_e - R_t)}_{\text{timing}} +
\underbrace{(R_t - R_r)}_{\text{selection}}.$$

Each part is shown with a bootstrap interval, because on a hundred bets
most of them are within noise, and the card says so. Timing includes
exits: a bet sold before the close differs from the rule's hold to
settlement.

## The report card (task 96)

The card is on `#shadow` and follows the two reading levels:

- **Simple:** three sentences (how the record did against the prices
  taken, whether the market later agreed, and the one habit that cost the
  most), the rule found if any, with "Try it as a strategy", and the
  caveats.
- **Detailed:** every table above, the rule list with its held-out
  numbers, the decomposition, and the peer context.

The card exports as JSON and CSV.

**Peer context** comes from the venue's public leaderboard for the
record's main category. It is anonymised to percentiles of profit per
dollar traded among the listed addresses, with the caveats stated:

- the list shows the top only, and is survivorship by construction;
- profit on it is all-time and gross of fees;
- volume includes market making.

The platform's own leaderboards (Phase 18) are added once they have
ranked entries.

## A signal from skilled addresses? (task 97)

"Follow the positions of consistently skilled addresses" is a hypothesis,
not a plan. It enters the library only through Phase 16's gates:

- a pure function of what was public at the cutoff;
- a formation window that selects the addresses strictly before the
  evaluation window;
- the bench against the market, with the needed-n.

The report tests it once on the weather category:

- **Formation:** the addresses are chosen by their CLV on bets closed
  before a date.
- **Evaluation:** their bets after the date are scored.

The report says whether that is worth building.

## Where it lives

The engine does the analysis and never touches the platform:

- `vp/venues/polymarket.py` gains read-only account calls (`fetch_activity`,
  `fetch_positions`, `fetch_user_pnl`, `fetch_profile`, `fetch_leaderboard`);
- `vp/shadow/` holds `record.py` (bets from activity), `diagnostics.py`,
  `rules.py`, `counterfactual.py` and `card.py`;
- the command is `vp shadow <address> --root <data>`, for developers.

The platform imports as a job:

- the `shadow_import` job and the `shadow_imports` table (migration 0024:
  address, consent, proof, state, the card);
- `/api/shadow` routes and the `#shadow` page;
- "Try it as a strategy" opens the rule's spec in the confirm flow of
  Phase 15.
