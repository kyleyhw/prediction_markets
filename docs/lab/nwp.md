# Weather Markets Against the Forecast Models

**The question.** A daily temperature market asks whether a city's high
will fall in a one-degree bucket. Numerical weather prediction (NWP)
models publish that forecast for free, many times a day. Is the market
sharper than the models, a day before and two days before?

**Method.** The `nwp_forecast` signal turns the forecast the models had
issued before each market's cutoff, at the station the market resolves on,
into a probability for the bucket (`docs/evidence.md`). The signal bench
scores every signal against the market's own price on the same markets,
with a paired bootstrap interval on the Brier advantage.

## Results

```bash lab
vp signals bench --domain weather --hours 24
```

```text
climatology        n=  447 par      [-0.0197, +0.0020]
persistence        n=  447 par      [-0.0165, +0.0058]
bucket_normalised  n=  440 alive    [+0.0027, +0.0149]
nwp_forecast       n=  396 alive    [+0.0018, +0.0179]
nwp_ensemble       n=    0 too few
platt_market       n=    0 too few
isotonic_market    n=    0 too few
```

```bash lab
vp lab events --domain weather --signal nwp_forecast
```

```text
`nwp_forecast` against the market on 396 weather markets in 36 events, 24 h before settlement; Brier advantage (positive is better than the market).

| Resampling | Mean advantage | 95% interval | Verdict |
| :--- | ---: | :--- | :--- |
| by market | +0.0099 | [+0.0019, +0.0186] | better than the market |
| by event | +0.0099 | [+0.0005, +0.0189] | better than the market |
```

```bash lab
vp lab events --domain weather --signal bucket_normalised
```

```text
`bucket_normalised` against the market on 440 weather markets in 40 events, 24 h before settlement; Brier advantage (positive is better than the market).

| Resampling | Mean advantage | 95% interval | Verdict |
| :--- | ---: | :--- | :--- |
| by market | +0.0088 | [+0.0027, +0.0148] | better than the market |
| by event | +0.0088 | [+0.0057, +0.0121] | better than the market |
```

```bash lab
vp signals bench --domain weather --hours 48
```

```text
climatology        n=  447 par      [-0.0070, +0.0156]
persistence        n=  447 par      [-0.0064, +0.0165]
bucket_normalised  n=  440 alive    [+0.0111, +0.0254]
nwp_forecast       n=    0 too few
nwp_ensemble       n=    0 too few
platt_market       n=    0 too few
isotonic_market    n=    0 too few
```

## What It Means

- **A day out, the forecast models' signal scored better than the
  published weather prices:** a Brier advantage of +0.0099 on 396 markets.
  Resampled by event, which is the honest interval since a day's buckets
  move together, it is +0.0005 to +0.0189 over only 36 events. That is
  above zero, but only just.
- **Simply rescaling the market's own bucket prices to sum to one does
  nearly as well:** +0.0088, and more robustly (+0.0057 to +0.0121 by
  event). The longshot study shows why: a day's published prices summed
  to 1.8 at the median. Part of the forecast's advantage is therefore an
  advantage over stale prices, which any consistent set of prices would
  have.
- **Two days out, no forecast was public yet.** The archive keeps
  forecasts issued one and two days ahead, and each counts only from its
  issue time plus six hours for delivery (`docs/evidence.md`). None was
  visible at a 48-hour cutoff, and the signal rightly answered nothing.
  The rescaled prices were ahead again.

So the market's published weather prices are beatable as a benchmark,
but whether the models know more than the market's consistent prices is
not shown. The test that would show it is the forecast signal against the
rescaled prices, on many more events, and then a forward paper record.

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
- **Point-in-time is the whole point.** The archive shows the signal only
  forecasts issued before the cutoff, allowing for the time the provider
  takes to publish (`docs/evidence.md`, the fetch-latency rule). A study
  that used the forecast as it stands today would see the answer.
- **The free forecast hosts limit requests,** and a station whose runs
  could not be fetched has no forecast, so fewer markets are scored than
  have a price.
- **One provider's models.** Other providers, or the ensemble spread,
  might be sharper; this is the signal the library has.
