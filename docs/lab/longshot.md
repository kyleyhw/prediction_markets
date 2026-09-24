# The Favourite-Longshot Bias

**The question.** On betting exchanges and at racetracks, long shots
famously win less often than their odds imply and favourites more often.
Does a Polymarket contract priced at 10¢ win one time in ten, a day
before it settles?

**Method.** Every settled market with a price history is placed in a bin
by its price 24 hours before settlement. For each bin the table gives how
many markets, their mean price, how often the event happened with a 95%
Wilson interval, and what buying every contract in the bin would have
returned per dollar: at the price plus a cent, paying the market's own
fee. A market whose prices are calibrated has "Won" close to "Mean price"
in every row, and every row loses about the cent and the fee.

## Results

```bash lab
vp lab longshot --domain epl
```

```text
408 labelled epl markets with a price 24 h before settlement; buying at the price plus 0.01 and the market's fee.

| Price bin | Markets | Mean price | Won | 95% interval | Return per $1 at the ask |
| :--- | ---: | ---: | ---: | :--- | ---: |
| 0.00 to 0.05 | 167 | 0.005 | 0.006 | [0.001, 0.033] | -0.831 |
| 0.05 to 0.15 | 38 | 0.100 | 0.079 | [0.027, 0.208] | -0.461 |
| 0.15 to 0.30 | 88 | 0.235 | 0.261 | [0.181, 0.362] | +0.013 |
| 0.30 to 0.50 | 55 | 0.407 | 0.327 | [0.218, 0.459] | -0.203 |
| 0.50 to 0.70 | 34 | 0.574 | 0.529 | [0.367, 0.685] | -0.108 |
| 0.70 to 0.85 | 8 | 0.791 | 0.625 | [0.306, 0.863] | -0.245 |
| 0.85 to 0.95 | 7 | 0.891 | 1.000 | [0.646, 1.000] | +0.108 |
| 0.95 to 1.00 | 11 | 0.984 | 1.000 | [0.741, 1.000] | +0.014 |

76 events of mutually exclusive markets had every market priced; their prices summed to 1.005 at the median (middle half 0.995 to 1.005), where fair prices sum to 1.

Market Brier 0.1073, reliability 0.0051, resolution 0.0640.
```

```bash lab
vp lab longshot --domain cs2
```

```text
198 labelled cs2 markets with a price 24 h before settlement; buying at the price plus 0.01 and the market's fee.

| Price bin | Markets | Mean price | Won | 95% interval | Return per $1 at the ask |
| :--- | ---: | ---: | ---: | :--- | ---: |
| 0.00 to 0.05 | 4 | 0.019 | 0.000 | [0.000, 0.490] | -1.049 |
| 0.05 to 0.15 | 9 | 0.096 | 0.000 | [0.000, 0.299] | -1.045 |
| 0.15 to 0.30 | 10 | 0.243 | 0.000 | [0.000, 0.278] | -1.037 |
| 0.30 to 0.50 | 52 | 0.408 | 0.346 | [0.232, 0.482] | -0.224 |
| 0.50 to 0.70 | 96 | 0.580 | 0.562 | [0.463, 0.657] | -0.086 |
| 0.70 to 0.85 | 25 | 0.767 | 0.760 | [0.566, 0.885] | -0.034 |
| 0.85 to 0.95 | 2 | 0.883 | 1.000 | [0.342, 1.000] | +0.116 |

Market Brier 0.1953, reliability 0.0109, resolution 0.0614.
```

```bash lab
vp lab longshot --domain weather
```

```text
475 labelled weather markets with a price 24 h before settlement; buying at the price plus 0.01 and the market's fee.

| Price bin | Markets | Mean price | Won | 95% interval | Return per $1 at the ask |
| :--- | ---: | ---: | ---: | :--- | ---: |
| 0.00 to 0.05 | 155 | 0.012 | 0.000 | [0.000, 0.024] | -1.049 |
| 0.05 to 0.15 | 60 | 0.089 | 0.017 | [0.003, 0.089] | -0.922 |
| 0.15 to 0.30 | 180 | 0.209 | 0.117 | [0.078, 0.172] | -0.527 |
| 0.30 to 0.50 | 66 | 0.390 | 0.242 | [0.155, 0.358] | -0.362 |
| 0.50 to 0.70 | 7 | 0.585 | 0.571 | [0.250, 0.842] | -0.110 |
| 0.70 to 0.85 | 1 | 0.810 | 1.000 | [0.207, 1.000] | +0.211 |
| 0.85 to 0.95 | 3 | 0.920 | 1.000 | [0.439, 1.000] | +0.073 |
| 0.95 to 1.00 | 3 | 0.989 | 1.000 | [0.439, 1.000] | +0.011 |

41 events of mutually exclusive markets had every market priced; their prices summed to 1.805 at the median (middle half 1.067 to 2.244), where fair prices sum to 1.

Market Brier 0.0786, reliability 0.0110, resolution 0.0247.
```

## What It Means

- **Premier League (408 markets): no bias.** In every price bin the share
  that won is within its interval of the mean price, and buying a whole
  bin loses about what the cent and the fee cost, apart from bins too
  small to say. The three results of a match priced to 1.005 at the
  median: consistent prices.
- **CS2 (198 markets): a hint of one, among the long shots.** None of the
  23 contracts priced under 30¢ won, where their prices added up to about
  3.4 expected wins. Each bin's interval still reaches its price, so this
  is a lead to watch as markets settle, not a finding.
- **Weather (475 markets): cheap buckets won far less often than priced.**
  Buckets priced around 21¢ won 11.7% of the time and those around 39¢
  24%, both outside their intervals. But **a day's buckets were priced at
  1.805 in total at the median**, where fair prices sum to one. The price
  series the venue publishes for a thin bucket keeps its last trade, and
  those last trades do not add up to a consistent set of prices. So what
  looks like a longshot bias here is, at least in part, stale prices. It
  is not a gap anyone could necessarily have traded: the table buys at the
  published price, and a real buyer pays the ask.

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
- **Bins with few markets are noise.** The Wilson interval is shown for
  that reason; a row whose interval covers its mean price shows no bias,
  whatever its point estimate.
- **Buying every contract in a bin is not a strategy anyone would run**,
  and its return is only a summary of calibration net of costs.
- **Many markets of one event move together.** The buckets of one day's
  weather, or the results of one match, are not independent, so the
  intervals are narrower than they should be.
