# Paper Trading

Phase 10 runs the forecasters forward: at the present, on open markets,
against the real order book, with settlement read from the venue. It is the
honest counterpart of the backtest, and the comparison between the two is
the leakage check.

## The Ledger

`vp.paper.ledger.Ledger` is an append-only JSONL file in which every entry
carries the SHA-256 of the previous entry and of its own content. Editing,
deleting or reordering any entry breaks every hash after it, and `verify()`
returns the first broken sequence number; the CLI refuses to run on a broken
chain. All paper-trading state (bankrolls, open positions) is derived by
replaying the ledger, so it is the only store, a fresh process resumes where
the last one stopped, and a corrected fact is a new entry that says so. The
same ledger design is what live execution will write to, which is why it is
built and tested before any execution code exists.

Entry kinds: `cycle` (a run started: domain, snapshot file, market count),
`forecast` (forecaster, market, $\hat p$, cost, market price), `order`
(side, effective price, shares, stake, fee paid, fee rate and its source,
bankroll before), `settlement`
(label, profit, Brier score of the forecast and of the market price,
bankroll after).

## One Cycle

`vp paper run --domain cs2 weather epl --forecasters market elo climatology`:

1. **Snapshot** the domain's open markets with book depth, through the same
   collector as the data layer, so the snapshot series keeps accumulating.
2. **Evidence at now.** The resolved sets give results and observations up
   to the present; nothing after it exists, so the forward loop cannot look
   ahead by construction.
3. **Forecast** every parsed market with each forecaster; append to the
   paper registry and the ledger.
4. **Order** against the real touch: buy the first outcome at its best ask,
   or the complementary share at one minus the best bid, sized by fractional
   Kelly on the forecaster's own paper bankroll, filled for at most the
   resting size at the touch. One open position per forecaster per market.
   The `market` forecaster never orders: it has no edge over itself and
   serves as the reference score.
5. **Fees** are the market's own taker fee, read from its `feeSchedule`
   with the snapshot, through the same `FeeModel` the backtest uses
   (`docs/sizing.md`): $C \cdot r \cdot (p(1 - p))^{e}$, 1.25 cents a share
   at 50 cents on today's sports and weather rate of 0.05. Sizing sees the
   effective price with the fee in it, and the order records the dollars
   paid. A market that states no rate falls back to the caller's model and
   the order says `assumed`. Orders written before 2026-09-23 paid none.

Each forecaster keeps a separate paper account so they are compared on
equal footing.

## Settlement

`vp paper settle` fetches each open position's market by condition id, the
CLOB path that carries the venue's `winner` flag, and settles those the
venue has resolved: a share of the winning side pays 1, so the profit is
shares minus stake on a win and minus the stake on a loss. The stake
includes the fee, so the profit is net of it. Pending markets
stay open; a void resolution (no winner) is counted and left open for a
later decision. Every settlement entry records the Brier score of the
forecast and of the market price at order time, which is how forward skill
is scored with the same code as the backtest.

## Leakage Check

`vp paper leakage --domain epl --backtest data/backtests/epl/<stamp>`
compares, per forecaster, the mean Brier score of the backtest run with the
mean Brier score of settled forward positions, and bootstraps a 95%
interval on the gap (forward minus backtest). A gap whose interval excludes
zero means the backtest was optimistic, and the only way it can be is
information from after its cutoffs. For the LLM forecaster in particular
this is the measurement of memory leakage that no prompt can rule out. The
check is fair within a domain and for the same forecaster configuration; it
prints both sample sizes and both scores because the two market samples can
differ in base rate.

## Operating It

The loop is a single cycle per invocation, so scheduling is external
(cron, or a Claude Code Routine). A sensible cadence is one `run` per hour
per domain and one `settle` per hour; every cycle is idempotent with
respect to open positions. Paper accounts start at 1,000 units and compound.
