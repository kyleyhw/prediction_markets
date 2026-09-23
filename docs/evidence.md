# The Evidence Archive

Evidence indexed by time only accumulates forward. This morning's weather
forecast cannot be downloaded next year as it stood this morning, and a
backtest may only use evidence as it stood before its cutoff (plan,
principle 5). So the collectors started in Phase 13 (task 33), long before
the forecasters read them in Phase 17: every week not captured is a week no
backtest can use honestly.

This page is where each source's terms are recorded before its collector
runs against production (flag F9). The readers, the point-in-time query
rules and the per-domain evidence design are Phase 17's, and extend this
page then.

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
| `gdelt` | Per domain, up to 50 headlines from the last 24 hours matching the domain's own keywords (title, URL, time seen, outlet, language) | GDELT data is free and open with attribution; requests limited to one every five seconds, which a token bucket enforces | Usable with attribution; headlines are stored as titles and links, not article text. |

Sources considered and not collected: football-data providers' free
tiers (rate and redistribution limits), Liquipedia (attribution and
share-alike on its text), and anything that requires scraping pages whose
terms forbid it. Match schedules for Counter-Strike come from the venue's
own listings instead.

## Withdrawal

Every capture is a separate object with its source in the key and in
`evidence_captures`, so a source whose terms change can be withdrawn with
all its rows: delete the objects under `shared/evidence/<source>/` and the
index rows, and nothing else is affected.
