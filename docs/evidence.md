# The Evidence Archive

Evidence indexed by time only accumulates forward. This morning's weather
forecast cannot be downloaded next year as it stood this morning, and a
backtest may only use evidence as it stood before its cutoff (plan,
principle 5). So the collectors started in Phase 13 (task 33), long before
the forecasters read them in Phase 17: every week not captured is a week no
backtest can use honestly.

This page is where each source's terms are recorded before its collector
runs against production (flag F9), and, since Phase 17, how forecasters
read the archive without seeing anything after their cutoff.

## How a capture is stored

A collector runs inside the `evidence` job, hourly (migration 0005,
schedule `evidence`). Each run of each source writes one Parquet file:

    shared/evidence/<source>/<YYYY-MM-DD>/<stamp>.parquet

and one row in `evidence_captures` (source, domain, capture time, object
key, rows, bytes). Every row in the file carries `captured_at`, the moment
we saw it, which is the time a reader compares with a cutoff. Nothing is
ever rewritten; a later capture of the same thing is a new file. A source
that fails is reported in the job's result and does not stop the others.

## Sources and their terms

| Source | What is captured | Terms | Status for production |
| :--- | :--- | :--- | :--- |
| `open_meteo` | For every city the open weather markets name: the 16-day forecast of daily high and low, one request for all cities; coordinates from Open-Meteo's geocoding, cached | Free API for non-commercial use (open-meteo.com terms); commercial use needs a paid plan; CC BY 4.0 attribution for the data | **Paid plan required before real users (F9).** Development capture is non-commercial. |
| `openfootball` | The Premier League season's fixtures and results from the openfootball `football.json` repository | Public domain (CC0 1.0) | Usable as is. |
| `venue_schedules` | The question, event and closing time the venue lists for every tracked market, from our own market registry | The venue's public market data, already collected by the market-data service under its terms | Usable as is; lawful access is flag F1's question for the deploy region. |
| `open_meteo_runs` | Hourly 2 m temperature as predicted one and two days before, at each named station, aggregated to the local day's maximum and minimum; backfilled from January 2024 | As `open_meteo`; the Previous Runs API is part of the same service | **Point-in-time provider**; paid plan before real users (F9). |
| `open_meteo_ensemble` | 51 ECMWF members of daily maximum and minimum for the next seven days at each station | As `open_meteo` | Paid plan before real users (F9). |
| `stations` | Each named station's coordinates, elevation and country | Aviation Weather Center (NOAA), US government work, public domain | Usable as is. |
| `gdelt` | Per domain, up to 50 headlines from the last 24 hours matching the domain's own keywords (title, URL, time seen, outlet, language) | GDELT data is free and open with attribution; requests limited to one every five seconds, which a token bucket enforces | Usable with attribution; headlines are stored as titles and links, not article text. |

Sources considered and not collected: football-data providers' free
tiers (rate and redistribution limits), Liquipedia (attribution and
share-alike on its text), and anything that requires scraping pages whose
terms forbid it. Match schedules for Counter-Strike come from the venue's
own listings instead.

## Reading the archive (Phase 17, task 72)

The engine reads captures from `<root>/evidence/<source>/<date>/`, the
same layout the platform writes under `shared/evidence/`, so the
platform's job roots link the directory in and the command line writes
it directly (`vp/forecast/archive.py`).

- **Manifest.** Beside each `<stamp>.parquet` is `<stamp>.json`: the
  source, the capture time, the row count, the file's SHA-256, the
  source's licence line and provenance (the request made, without keys),
  and the visibility rule. A capture whose hash does not match its
  manifest is not read.
- **Visibility.** A row is visible to a forecaster with cutoff $c$ only if
  its `available_at` is before $c$. `available_at` is `captured_at`
  unless the source is a **point-in-time provider**: one that keeps each
  value as it was issued, never revised, and documents when it was
  issued. Only such a source may be backfilled, and each backfilled row
  carries the latest moment the value can have existed, computed from the
  provider's documented definition, never an earlier guess. The sources
  that qualify are listed in the table below; today there is one.
- **Accessors.** Each source gets an accessor on `Evidence`
  (`nwp`, `ensemble`, `headlines`, `fixtures`), so no forecaster or signal
  reads files; the purity gate and the cutoff sentinel of
  `docs/signals.md` cover the new accessors with fixture captures made
  after the sentinel's cutoff.
- **Retention.** Captures are small and kept for as long as the source's
  terms allow; headlines are kept as titles and links, never article
  text. Withdrawal is below.

## Weather (task 73)

A weather market names its station: the venue's resolution source is
NOAA's time series for an airport (`weather.gov/wrh/timeseries?site=eglc`
for London City) or Weather Underground's page for one, both keyed by the
station's ICAO code. Markets now keep that URL (`resolution_source`), the
weather domain reads the station from it, and the station's coordinates
come from the Aviation Weather Center's station list (US government,
public domain), so forecasts are read at the station that decides the
market, not at a geocoded city centre.

- **`open_meteo_runs`, point in time.** Open-Meteo's Previous Runs API
  keeps each model's forecasts as issued, from January 2024; it defines
  `temperature_2m_previous_dayN` as "the value that was predicted N×24
  hours before valid time". An hourly value for time $t$ therefore existed
  by $t - 24N$ hours plus the run's delivery; the archive allows six hours
  for delivery, so a day's maximum or minimum from `previous_dayN` has
  `available_at` = the last hour of the local day $- 24N + 6$ hours. The
  backfill (`vp evidence weather-runs`) reads days one and two for every
  station a market has named; the collector adds each new day.
- **`open_meteo_ensemble`, forward only.** The Ensemble API's members
  (ECMWF IFS, 51 members) for the next days at each station, captured
  hourly with `available_at = captured_at`, since the provider keeps no
  history of it; a backtest can use it only from the first capture on.
- **Observations** for labels and climatology stay what they were: the
  resolved markets themselves (closed is not resolved).
- **The rate limit of 2026-09-13.** Open-Meteo's free endpoints limit by
  address, and this container shares one with others. Decided as proposed:
  production uses the paid API with its key (`VP_OPEN_METEO_KEY`, sent to
  the `customer-` hosts), which F9 already requires; the backfill here
  retries 429s with a pause and resumes from what it has.

Signals from them (`docs/signals.md`): `nwp_forecast`, the bucket's
probability under the point-in-time forecast plus the station's own error
distribution fitted on earlier settled days; `nwp_ensemble`, the share of
members in the bucket after the same bias correction.

## Football (task 74)

Fixtures and results come from openfootball (CC0), captured daily and
also readable for past seasons, since a result is a fact with a date: a
match's result is visible from its kick-off plus three hours. League
tables are derived from those results at the cutoff, never fetched.
Line-ups and injuries have no open source with point-in-time semantics
whose terms were confirmed for this use: football-data.org answers 403
without a key and its free tier limits rate and redistribution, and the
sites that publish line-ups are scrape-hostile. They stay out until a
licensed feed is chosen and paid for (F9).

## Counter-Strike (task 75)

Schedules and results come from the venue's own listings and its
resolved markets. Liquipedia is the candidate for rosters and map vetoes:
its data API (LPDB) needs a key applied for by the operator, and its wiki
API refuses requests that are not gzip-encoded and points to its API
terms (liquipedia.net/api-terms), which did not load from this container
on 2026-09-23 and must be read before any collector is written. Decided as
proposed: the operator applies for an LPDB key and records the terms here;
until then nothing from Liquipedia is collected. HLTV forbids automated
access and is not used.

## Headlines (task 76)

`headlines(domain, hours)` returns the GDELT titles captured before the
cutoff, newest first; the LLM forecaster puts up to ten in its prompt
under "Headlines captured before the cutoff". Web search at forecast time
is allowed only in the forward loop, where the present is the cutoff, and
is logged with the forecast; a backtest never searches.

## Withdrawal

Every capture is a separate object with its source in the key and in
`evidence_captures`, so a source whose terms change can be withdrawn with
all its rows: delete the objects under `shared/evidence/<source>/` and the
index rows, and nothing else is affected.
