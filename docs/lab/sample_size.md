# How Many Settled Markets Does a Claim of Edge Need?

**The question.** A strategy shows a positive skill against the market
over its first few dozen settled markets. How many markets does it take
before that could be anything but luck?

**Method.** Each baseline and the market are scored on the same markets a
day before settlement. The per-market difference of their Brier scores
varies a great deal from market to market, and its spread fixes how many
markets a real edge of a given size needs to show at 95% confidence with
80% power: $n = \left((z_{0.95} + z_{0.80})\,\sigma / \delta\right)^2$, where
$\sigma$ is the spread and $\delta$ the edge in Brier points. The second
table does the same for betting: a bootstrap needs about
$(1.645 / S)^2$ bets before it gives a per-bet Sharpe ratio $S$ a 95%
chance of being positive.

## Results

```bash lab
vp lab power --domain epl --forecaster elo
```

```text
`elo` against the market on 132 epl markets, 24 h before settlement.

Skill -0.0065, 95% interval [-0.0762, +0.0632]. Per-market Brier difference: mean +0.0014, standard deviation 0.0871; the market's mean Brier 0.2132.

| True skill against the market | Markets needed (95% confidence, 80% power) |
| ---: | ---: |
| +0.01 | 10,315 |
| +0.02 | 2,579 |
| +0.05 | 413 |
| +0.10 | 104 |

| Per-bet Sharpe | Bets for P(Sharpe > 0) of 0.95 |
| ---: | ---: |
| 0.05 | 1,083 |
| 0.10 | 271 |
| 0.20 | 68 |
```

```bash lab
vp lab power --domain cs2 --forecaster elo
```

```text
`elo` against the market on 143 cs2 markets, 24 h before settlement.

Skill -0.1031, 95% interval [-0.1785, -0.0277]. Per-market Brier difference: mean +0.0220, standard deviation 0.0983; the market's mean Brier 0.2137.

| True skill against the market | Markets needed (95% confidence, 80% power) |
| ---: | ---: |
| +0.01 | 13,085 |
| +0.02 | 3,272 |
| +0.05 | 524 |
| +0.10 | 131 |

| Per-bet Sharpe | Bets for P(Sharpe > 0) of 0.95 |
| ---: | ---: |
| 0.05 | 1,083 |
| 0.10 | 271 |
| 0.20 | 68 |
```

```bash lab
vp lab power --domain weather --forecaster climatology
```

```text
`climatology` against the market on 447 weather markets, 24 h before settlement.

Skill -0.1067, 95% interval [-0.2473, +0.0338]. Per-market Brier difference: mean +0.0084, standard deviation 0.1195; the market's mean Brier 0.0788.

| True skill against the market | Markets needed (95% confidence, 80% power) |
| ---: | ---: |
| +0.01 | 142,203 |
| +0.02 | 35,551 |
| +0.05 | 5,689 |
| +0.10 | 1,423 |

| Per-bet Sharpe | Bets for P(Sharpe > 0) of 0.95 |
| ---: | ---: |
| 0.05 | 1,083 |
| 0.10 | 271 |
| 0.20 | 68 |
```

## What It Means

Telling a real edge from luck takes far more settled markets than it
feels like it should, because a single market's score swings much more
than any plausible edge.

- **Premier League:** the per-market Brier difference between Elo and the
  market has a standard deviation of 0.087, against a mean of 0.001. A
  true skill of +0.05 needs about 413 markets to show; +0.02 needs 2,579.
  Elo has 132.
- **CS2:** +0.05 needs 524 markets.
- **Weather:** the market's Brier score is small (0.079), so the same
  relative skill is a smaller absolute gap: +0.05 needs about 5,689
  markets, more than ten times as many.
- **Betting:** a per-bet Sharpe ratio of 0.1, which is a very good one,
  needs about 271 bets before the bootstrap is 95% sure it is positive.

The platform's own rules follow from this. The leaderboards rank nothing
under 50 settled positions (`docs/collaboration.md`), which is a floor,
not proof. Before a strategy could go live, the promotion protocol asks
for a forward paper advantage whose interval excludes zero, or at least
100 settled markets with a positive advantage (`docs/portfolio.md`,
criterion 3). A strategy's preview states how many bets its edge would
need.

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
- **The spread is estimated from few markets,** so the markets needed are
  themselves uncertain, by a factor of two either way with a few dozen
  markets; the order of magnitude is the finding.
- **Markets of one event are not independent,** which makes the true
  number needed larger than the formula says.
- **Power, not proof.** A strategy that clears the bar with these many
  markets has shown an edge on the past; the paper record is still the
  test (`docs/portfolio.md`, the promotion protocol).
