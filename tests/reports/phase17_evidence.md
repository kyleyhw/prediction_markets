# Phase 17 Test Report: Evidence Archive, Point-in-Time Sources and New Domains

Date: 2026-09-23. Environment: Python 3.14.7 via `uv 0.12.18`, Postgres 16
in the development container, the live venue and evidence providers over
the container's proxy. Datasets rebuilt from the venue that evening
(146,595 weather, 14,565 Premier League and 93,416 CS2 markets, all now
carrying each market's fee rate, resolution source and negative-risk
fields), with the 400 price histories per domain of the Phase 9 sample.

## Purpose

Evidence is where forecasting skill comes from and where leakage hides.
The phase makes the archive readable by forecasters only up to their
cutoff, adds the point-in-time sources that let a backtest see evidence as
it stood, re-runs the baselines with the fees the venue actually charges,
re-verifies the venue's interfaces, and turns opening a domain into a
procedure. The design went into `docs/evidence.md` and `docs/domains.md`
first; the decisions (the Open-Meteo paid plan and key, the Liquipedia key,
football line-ups deferred, the domain ranking) were taken as proposed.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |
| `pytest -q` | 320 passed (308 before the phase) | 26 s |

| File | Tests | What |
| :--- | ---: | :--- |
| `test_archive.py` | 8 | rows are served only once visible, a backfilled row only an hour after its bound unless captured sooner, and a point-in-time row by its issue bound, not its fetch time; only a point-in-time source may carry that bound; a capture whose file does not match its manifest is not read; weather markets name their station; hourly runs become local days with the right bound across a clock change; the weather-model signals read what was issued before the cutoff; the LLM tools read the archive; the table counts only results known before the cutoff |
| `test_domain_boundary.py` | 1 | no code outside `vp/domains/` names a domain (Python and the interface's scripts) |
| `test_domain_kit.py` | 1 | a domain defined only by its adapter reaches the strategy spec, the signals and the evidence |
| `test_signals.py` | +2 | the two new signals pass purity, metadata and the cutoff sentinel, whose fixtures now include archive captures after the cutoff |
| `test_platform_evidence.py` | changed | the new collectors write manifests; a point-in-time row not yet final is not written |
| `test_platform_ingest.py` | changed | reconciliation asks again about resolutions stored without their answer |
| `test_polymarket.py` | changed | the v2 resolution and history shapes as measured |

## The Archive (task 72)

`vp/forecast/archive.py` reads `<root>/evidence/<source>/<date>/`, the
layout the platform writes, and `Evidence` gains `nwp`, `ensemble`,
`headlines` and `table`; no forecaster reads a file. Each capture has a
manifest (rows, SHA-256, licence, the request made); a mismatched file is
skipped. A row is visible before a cutoff by `captured_at`, or, for the
two point-in-time sources, by `available_at`, the latest moment the value
can have existed; a row whose moment has not come is never written.

## Weather (task 73)

Of 143,281 daily-temperature markets, 127,342 (89%) name their station in
the venue's resolution source; the rest predate the field. They name 53
stations. Paris moved from Le Bourget (LFPB) to Charles de Gaulle (LFPG)
and Denver from KDEN to KBKF over the period, so the station is read per
market, never per city.

| Source | Coverage | Freshness | Runtime |
| :--- | :--- | :--- | ---: |
| `stations` (NOAA) | 53 of 53 codes | static | not timed |
| `open_meteo_runs` backfill | 53 stations, 32,203 rows (day and lead), 2024-10-24 to 2026-09-24 | tomorrow two days ahead for all 53 at 20:51 UTC; one day ahead as each becomes final | 745 s, then 77 s for the forward pass |
| `openfootball` | 3 seasons, 1,140 matches | results from kick-off plus three hours | not timed |
| `open_meteo_ensemble` | 47 stations with an open market, 16,779 member rows (51 members, 7 days) | forward only, first capture 2026-09-23 21:33 UTC | 71 s |

The Previous Runs API answered 429 and timed out through the evening
(the container shares its address); the backfill paused and resumed, two
stations needed a second run, and all 53 completed. `recheck` read the
last 30 days of every station again the same evening: 3,162 rows compared,
none changed.

## The Weather Model Against the Market

`vp signals bench --domain weather` on the Phase 9 sample, 24 hours before
settlement, with the archive's final visibility rule (below):

| Signal | n | Brier | Market | Skill | Advantage [95%] | Verdict | Reliability |
| :--- | ---: | ---: | ---: | ---: | :--- | :--- | ---: |
| `nwp_forecast` | 271 | 0.0683 | 0.0691 | +0.012 | +0.0008 [−0.0095, +0.0110] | par | 0.0033 |
| blend: `nwp_forecast` | 169 | 0.0732 | 0.0762 | +0.039 | +0.0030 [−0.0066, +0.0124] | par | 0.0039 |
| `climatology` | 348 | 0.0788 | 0.0665 | −0.185 | −0.0123 [−0.0264, +0.0002] | par | 0.0143 |

The numerical forecast is the first weather signal level with the market
a day out; climatology was well behind it. It is also better calibrated
than the market on the same markets (reliability 0.0033 against 0.0057).
An advantage that small could not be told from zero on fewer than about
80,000 markets. Six hours out the market, which by then has most of the
day's readings, is far ahead (Brier 0.0256 against 0.0661).

As a strategy, `vp backtest --forecasters market signal:nwp_forecast
--min-edge 0.05 --market-fees`, 24 hours out: 97 bets, +123%, win rate
49%, per-bet Sharpe 0.122 with a bootstrap interval of [−0.160, 0.233],
$P(\text{Sharpe} > 0) = 0.90$. Six hours out: 121 bets, −94%.

**How far to trust the day-out result.** The first run, before the
fetch-latency rule, gave skill +0.027 and +181%; the rule moved some
markets from the forecast issued a day ahead to the one issued two days
ahead and cut both. Made stricter still, every forecast visible twelve
hours after its bound, the signal is no worse (249 scored, skill +0.026,
91 bets, +190%, $P(\text{Sharpe} > 0) = 0.93$), so the result does not
rest on the timing allowance. It is still not established: every Sharpe
interval includes zero, the simulator fills at the last price plus one
cent, and weather books are thin. It is the first candidate the platform
has for its forward test, paper trading at the real book.

## Football, CS2, Headlines (tasks 74 to 76)

The derived Premier League table at the end of 2024-25 reads Liverpool
84, Arsenal 74, Manchester City 71, Chelsea 69, the real final table's
top four. Line-ups and injuries are not collected (no source whose terms
were confirmed). Liquipedia's API terms page did not load from the
container and its data API needs a key the owner must apply for, so
nothing from Liquipedia is collected. GDELT answered 429 here as in Phase
13, so the headline accessor and the LLM tool are tested on fixtures only.

## Fees (task 77)

The venue sets each market's rate: zero before spring 2026, then 3% or 5%
by domain and month. With `--market-fees` the Phase 9 baselines lose four
to five points more on each sports baseline; the scores are unchanged.
The Phase 9 report carries the full table as an amendment, and a
correction: its "no bet at 5% edge" for weather climatology was wrong
(the report's own commit places 244 bets on the same data).

## The Venue (task 78)

Every line of the client's endpoint table was read again live. Two faults
found and fixed: the Data API v2 history fallback sent no time component
and was refused (HTTP 400); and the v2 resolution record carries the
oracle's answer as an 18-decimal `price`, not `payouts`, so the client
read no winner from any live record (of eight settled markets checked,
seven agree with the CLOB `winner` flags under the new reading, and the
eighth has no CLOB flag at all). The market-data service now asks again about any
resolution it stored without an answer. New fields on the record:
`resolution_source`, `neg_risk`, `neg_risk_market_id`; `comboStatus` was
`disabled` on every market sampled.

## Domains (task 79)

`docs/domains.md` is the kit; the boundary test found the places that
named a domain outside the adapters (the evidence reader, the research
assistant's tool, two collectors, the backfill and its command) and each now
uses a property of the domain (`observes`, `openfootball`, `zone`).
Candidates ranked from the venue's own counts: the four big European
football leagues first (each has openfootball results and about the
Premier League's volume), then the other esports titles, then the North
American leagues; opening any is the owner's decision.

## Leakage Audit

- The cutoff sentinel covers both new signals with archive captures after
  its cutoff: unchanged values.
- `recheck`: 3,162 point-in-time rows read again, none changed; across
  the evening's captures 475 rows were read more than once, none with a
  different value.
- **Forward against recomputed.** Forecasts for the 2,882 open weather
  markets were made at 21:34 UTC from the archive as it stood (1,639 from
  the model forecast, 2,497 from the ensemble), then recomputed at the same
  cutoff after one more capture. 296 of 4,136 differed. The cause: 15
  forecasts for the next day became final between the captures, their
  bound was before the cutoff, and the recomputation used them, although
  a forward run at 21:34 had not yet fetched them. That is backtest
  optimism, not future information, and it is fixed by the fetch-latency
  rule (`docs/evidence.md`): a backfilled row is visible an hour after its
  bound, a row captured sooner from its capture, and the weather collector
  runs hourly. Repeated under the rule, forecasts made at 21:58 and
  recomputed after a further capture of runs and ensemble: 4,136 of 4,136
  identical.
- The twelve-hour stricter re-run above.

## Found and Fixed

- A backtest could see point-in-time rows before a forward run would have
  fetched them (the leakage audit above); fixed by the fetch-latency rule.
- One station's network failure ended the whole ensemble capture, in the
  command and in the platform collector; each station now fails alone.

- The v2 history fallback and v2 resolution parsing (above).
- The daily collector read only the last three days, so it would never
  have captured the forecast for tomorrow's markets, the one the forward
  loop needs; it now reads through tomorrow and keeps what is final, and
  the backfill resumes with two days' overlap.
- Captures a collector wrote had no manifest; they now do.
- `vp backtest` accepted only five forecaster names although signals and
  blends have been beliefs since Phase 16; it now accepts any known name.
- The hard-coded domain names (above).

## Not Done

- The ensemble signal has no bench: the provider keeps no ensemble
  history, so it can be scored only on markets that settle after the first
  capture (2026-09-23, 47 stations).
- GDELT headlines and Liquipedia: blocked here (429) and waiting on the
  owner's key, respectively.
- Line-ups and injuries: waiting on a licensed feed.
- The Open-Meteo paid plan (F9) before real users.
- A forward-against-settled leakage comparison for the new signal needs
  its paper forecasts to settle.
