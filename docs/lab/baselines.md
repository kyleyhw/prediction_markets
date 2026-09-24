# Fee-Aware Baselines: Does Anything Simple Beat Polymarket?

**The question.** On the markets the platform covers, does any of its
simple baseline strategies forecast better than the market's own price a
day before settlement, and can it make money once each market's own fee
is paid?

**Method.** For every settled market with a price history, each baseline
forecasts from what was known 24 hours before settlement (the cutoff),
and so does the market: its price then. Scores are Brier scores on the
same markets; skill is how much lower a baseline's score is than the
market's, as a fraction of it. Then each baseline bets where it sees at
least five points of edge, at the price plus a cent, paying the market's
own taker fee, a quarter Kelly capped at 5% of a $1,000 play bankroll.

- `constant` says 50% on everything. It is the floor.
- `climatology` (weather) is how often each temperature bucket happened
  on that date in earlier years at that station.
- `elo` (football, esports) rates teams from earlier results.

## Results

```bash lab
vp backtest --domain weather --forecasters market constant climatology --market-fees --min-edge 0.05
```

```text
# Backtest: weather

forecasters: market, constant, climatology; cutoff 24.0 h before settlement; kinds all; seed 0
markets: 147281 selected, 475 with a price at the cutoff, 447 forecast by every forecaster (scored)

| Forecaster | n | Brier | Log | Skill vs market | Reliability | Resolution | ECE | Cost USD |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | 447 | 0.0788 | 0.2655 | +0.0000 | 0.0099 | 0.0141 | 0.0701 | 0.00 |
| constant | 447 | 0.2500 | 0.6931 | -2.1723 | 0.1667 | 0.0000 | 0.4083 | 0.00 |
| climatology | 447 | 0.0872 | 0.3094 | -0.1067 | 0.0104 | 0.0063 | 0.0494 | 0.00 |

Simulated bets from 1000, half-spread 0.01, each market's own taker fee, 0.25 Kelly, cap 5% per bet, minimum edge 0.05:

| Forecaster | Bets | Return | Max drawdown | Win rate | Profit factor | Per-bet Sharpe | Sharpe 95% CI | P(Sharpe > 0) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| constant | 428 | -100.00% | -100.00% | 8.41% | 0.15 | -0.636 | [-0.883, -0.459] | 0.00 |
| climatology | 275 | -72.28% | -72.48% | 53.09% | 0.76 | -0.118 | [-0.248, -0.003] | 0.02 |
```

```bash lab
vp backtest --domain epl --forecasters market constant elo --market-fees --min-edge 0.05
```

```text
# Backtest: epl

forecasters: market, constant, elo; cutoff 24.0 h before settlement; kinds all; seed 0
markets: 3408 selected, 408 with a price at the cutoff, 132 forecast by every forecaster (scored)

| Forecaster | n | Brier | Log | Skill vs market | Reliability | Resolution | ECE | Cost USD |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | 132 | 0.2132 | 0.6159 | +0.0000 | 0.0055 | 0.0146 | 0.0560 | 0.00 |
| constant | 132 | 0.2500 | 0.6931 | -0.1727 | 0.0278 | 0.0000 | 0.1667 | 0.00 |
| elo | 132 | 0.2146 | 0.6181 | -0.0065 | 0.0050 | 0.0136 | 0.0524 | 0.00 |

Simulated bets from 1000, half-spread 0.01, each market's own taker fee, 0.25 Kelly, cap 5% per bet, minimum edge 0.05:

| Forecaster | Bets | Return | Max drawdown | Win rate | Profit factor | Per-bet Sharpe | Sharpe 95% CI | P(Sharpe > 0) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| constant | 114 | -12.16% | -56.45% | 29.82% | 0.96 | 0.024 | [-0.166, 0.193] | 0.59 |
| elo | 60 | +13.10% | -30.38% | 45.00% | 1.10 | 0.064 | [-0.213, 0.308] | 0.69 |
```

```bash lab
vp backtest --domain cs2 --forecasters market constant elo --market-fees --min-edge 0.05
```

```text
# Backtest: cs2

forecasters: market, constant, elo; cutoff 24.0 h before settlement; kinds all; seed 0
markets: 29416 selected, 198 with a price at the cutoff, 143 forecast by every forecaster (scored)

| Forecaster | n | Brier | Log | Skill vs market | Reliability | Resolution | ECE | Cost USD |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | 143 | 0.2137 | 0.6154 | +0.0000 | 0.0158 | 0.0472 | 0.1175 | 0.00 |
| constant | 143 | 0.2500 | 0.6931 | -0.1696 | 0.0006 | 0.0000 | 0.0245 | 0.00 |
| elo | 143 | 0.2358 | 0.6679 | -0.1031 | 0.0274 | 0.0398 | 0.1369 | 0.00 |

Simulated bets from 1000, half-spread 0.01, each market's own taker fee, 0.25 Kelly, cap 5% per bet, minimum edge 0.05:

| Forecaster | Bets | Return | Max drawdown | Win rate | Profit factor | Per-bet Sharpe | Sharpe 95% CI | P(Sharpe > 0) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| constant | 94 | -66.97% | -73.29% | 28.72% | 0.68 | -0.165 | [-0.461, 0.012] | 0.04 |
| elo | 74 | -61.48% | -67.60% | 36.49% | 0.49 | -0.260 | [-0.563, -0.028] | 0.01 |
```

## What It Means

No baseline beats the market, on markets that settled recently and with
each market's own fee paid, which is what the Phase 9 report found on
older markets.

- **Weather:** climatology scores −0.107 against the market on 447
  markets and loses 72% of the play bankroll in 275 bets; the bootstrap
  gives its Sharpe ratio a 2% chance of being positive. Betting 50% on
  every bucket loses everything.
- **Premier League:** Elo is level with the market (−0.0065 on 132
  markets). Its bets made 13%, but with a 69% chance that the Sharpe ratio
  is positive, which is a coin that came up heads rather than an edge.
- **CS2:** Elo scores −0.103 on 143 markets and loses 61%.

The market is the bar a strategy has to clear, and on these numbers it is
a high one. Of the three domains, the Premier League is where a better
belief has the least distance to make up.

## Caveats

- **Which markets.** Price histories were fetched for the 500 most
  recently settled markets of each domain that a backtest scores by
  default (props last), so every number describes recent markets, not the
  venue's whole history, and the counts are small. Each table says how
  many markets it rests on; read nothing into a row with a handful.
- **The price is a traded price, not a quote.** The history is the
  venue's price series at 60-minute bars (daily for older markets), read
  at the last point at or before the cutoff. It can be stale for a thin market,
  and the spread at that moment is not recorded; the studies charge a
  one-cent half-spread everywhere, which is too little for a thin market
  and too much for a deep one.
- **Fees changed during the period.** The venue charged nothing before
  spring 2026, then 3% or 5% by domain and month (`docs/sizing.md`). Each
  market is charged its own recorded rate, so older markets pay none.
- **Settled is not the same as labelled.** Void or split markets carry no
  label and are left out (`docs/data_layer.md`), which removes exactly the
  markets where a bet would have been refunded.
- **The baselines are deliberately simple.** They are the floor a
  strategy must clear, not the best that can be done. That none clears the
  market says the market is not trivially beaten, not that it cannot be.
- **A return is one path.** The bankroll figures come from one ordering
  of the bets; the bootstrap interval on the Sharpe ratio is the honest
  summary, and "P(Sharpe > 0)" near 0.5 means nothing was shown.
