# Edge, Fees and Sizing

Phase 9 turns a forecast into a position. This page derives what
`vp.backtest.sizing` computes and states the fee model and its source.

## The Contract

A Polymarket market on outcome $A$ has two shares. The $A$ share pays 1 if
$A$ occurs and 0 otherwise and trades at $q$; the complementary share pays
the reverse and trades at about $1 - q$. Holding belief $\hat p$ that $A$
occurs, buying one $A$ share at the ask $a$ has expected value $\hat p - a$;
buying one complementary share at $1 - b$ (where $b$ is the bid for $A$) has
expected value $(1 - \hat p) - (1 - b) = b - \hat p$. Exactly one of these
can be positive when $\hat p$ lies outside the spread $[b, a]$; inside it
there is no trade.

## Fees

Polymarket charges a taker fee on some markets, set per market by the
protocol and applied at match time. Its documentation (docs.polymarket.com,
Trading → Fees, read 2026-09-13) states the fee on $C$ shares matched at
price $p$ as

$$\text{fee} = C \cdot r \cdot p\,(1 - p),$$

with $r$ the market's taker fee rate, published on the CLOB market object
as `taker_base_fee` in basis points. The form is symmetric and vanishes at
the extremes, so a fee is largest on a 50/50 contract and negligible on a
long shot. Sports and weather markets carried a zero rate when this was
written, and the backtest's default is zero; the live rate must be read
from the market, never assumed. The fee enters sizing through the effective
price $a' = a + r\,a(1 - a)$.

## Kelly

Buying an $A$ share at effective price $a'$ is a bet that returns $1$ on a
stake of $a'$: fractional odds $b = (1 - a')/a'$. For a bet won with
probability $p$ at odds $b$, the Kelly fraction of bankroll that maximises
the expected log growth $p \ln(1 + f b) + (1 - p) \ln(1 - f)$ is

$$f^* = p - \frac{1 - p}{b} = \frac{p - a'}{1 - a'},$$

obtained by setting the derivative $\frac{pb}{1 + fb} - \frac{1-p}{1-f}$ to
zero. It is positive exactly when there is edge ($p > a'$) and is 1 only at
certainty. For the complementary share the same expression holds with
$p \to 1 - \hat p$ and $a' \to (1 - b)'$.

Full Kelly assumes $\hat p$ is exact; with a mis-estimated probability it
overbets, and its bankroll paths have severe variance. The backtest and
paper trading stake a **quarter** of $f^*$, which for small edges gives up
about a quarter of the growth rate for a large reduction in drawdown, and
cap any single position at 5% of the bankroll so no one market can do
lasting damage and so stakes stay small relative to the books seen in
snapshots. The live mandate (Phase 11) will add absolute caps on top.

## Expected Value per Dollar

The `edge` field of a position is $(p - a')/a'$, the expected return per
dollar staked; it is what is compared across markets when a bankroll must
be rationed and is reported per bet in the ledger.

## Reference

- Kelly, J. L. (1956). A new interpretation of information rate. *Bell
  System Technical Journal* 35(4), 917–926.
