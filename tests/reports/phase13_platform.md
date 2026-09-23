# Phase 13 Test Report: Platform Foundation

Date: 2026-09-23. Environment: Python 3.14.7 via `uv 0.12.18`; the
platform under Docker Compose on the development container (4 cores,
15.7 GiB), with Postgres 16, MinIO, the web service in four processes, five
worker pools and the market-data service, all from the image built from
this repository; outbound traffic through the sandbox's proxy. This is the
local stand-in of flag F16: nothing here ran on the cloud host, and every
figure below is from this one machine.

## Purpose

Phase 13 wraps the engine in what many people need at once: accounts and
tenancy, storage in Postgres and an object store, a job queue with worker
pools, one market-data subscription for everyone, the evidence collectors,
budgets, observability and the operator's controls. The phase is done
when, on the stand-in, one person can sign in, see the dashboard's views
over live data the service ingests itself, run a backtest and a paper
cycle from the page, watch them progress and see what they cost, while a
second person sees none of it; and the measurements below are recorded.

## Static Checks

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .` and `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |

## Unit Tests

`uv run pytest -q`: 228 passed in about 10 s, against a Postgres test
database (`vp_test`, separate from the development database since the
fixtures delete rows). The platform files, what each proves, and why it
matters:

| File | What | Why |
| :--- | :--- | :--- |
| `test_platform_ledger.py` | the Postgres chain equals the file ledger's and an export verifies with `Ledger.verify`; another workspace sees nothing and cannot append; concurrent appends queue; a batch chains as single appends and lands whole or not at all; partitions are unreachable except through the parent; an archived month leaves Postgres and still verifies | the ledger is the only store of paper state and the model of the live audit trail |
| `test_platform_storage.py` | local and S3 stores (S3 through `moto`), dataset publishing, the shared cache and a job's working root | every engine path reads the cache |
| `test_platform_jobs.py` | claiming, leases, reaping, retries and the dead state, cancel, halts and drains, cron in a time zone, one scheduler per minute | the queue runs unattended |
| `test_platform_handlers.py` | a backtest and a paper cycle run by a worker into the right workspace; the cutoff is the capture's time and a second account reuses the memo; the market list shows only the workspace's forecasts; settlement asks the venue once for everyone; a dataset build never fetches a history twice | the engine under the service |
| `test_platform_ingest.py` | books from the channel's events; snapshots in the engine's format; quotes only for moved tops of first outcomes; resolutions with their delay; lag from change events only; staleness as socket silence; sockets filled before new ones open | one subscription serves everyone, so its figures must mean what they say |
| `test_platform_evidence.py` | each collector writes a capture with its time, including the bare score some openfootball matches carry | evidence only accumulates forward |
| `test_platform_ops.py` | halts, pauses, budgets, retries and drains, each in the audit chain with the operator; a refresh repeats the daily build; a job scheduled for later is not waiting | the operator's controls |
| `test_platform_llmops.py` | envelope encryption, key hints, the cross-process limiter | a person's key is never readable |
| `test_platform_work.py` | from the web: paper trading started, a backtest estimated, run and kept private, a model backtest needing a key and fitting the budget, an own key, spending, refresh, metrics; the paper view is never stale | the "done when" in requests |
| `test_platform_observe.py` | two processes' counters add up in one scrape | `vp serve --workers` |

## The Walk-Through in a Browser

Chromium, driven by Playwright against the Compose web service
(`http://127.0.0.1:8000`), with the sign-in link read from the service's
outbox. Screenshots were taken and checked; they live outside the
repository, as earlier phases' did.

| Step | Result |
| :--- | :--- |
| Ada signs in | the emailed link, the confirm page, the dashboard |
| Home offers paper trading; she accepts | account opened, two schedules in her time zone, first cycle queued; the jobs panel shows it with a progress bar ("trading cs2", "trading weather", "trading epl") |
| First cycle | 11,506 forecasts and about 2,740 orders over the capture of 5,000 parsed markets, 62 s on the first build, 7.5 s after the fixes below |
| A backtest from the page (weather, market price and climatology) | estimate shown before starting ("146,151 settled markets, free"), queued, progress by market, finished run opened: 1,891 markets scored, climatology Brier 0.088 against the market's 0.078, skill -0.14, and the page says the run assumed no fees |
| What it cost | Settings: "$0.00 of your $5.00 limit"; no model strategy was run, because the container holds no Anthropic key |
| Bob signs in | no account, no jobs, no backtests; Ada's job id answers 404 |
| Accessibility | axe-core, WCAG 2.0 to 2.2 A and AA: 21 page states (five views, both levels, both themes, and the backtest form with a job running): no violations |

One fault was found this way: the password field for one's own key kept the
browser's light background in the dark theme; fixed.

## Measurements

### Request latency

Load from a Python client with 16 threads over 60 s against four signed-in
people who each hold a paper account of about 14,000 ledger entries, on a
mix of the dashboard's reads (overview, paper, jobs, spend, capabilities,
backtests, and the Premier League and weather market lists).

| Build | Processes | Concurrent | Requests/s | p50 | p95 | p99 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| as first built | 1 | 16 | 5.9 | 1,492 ms | 7,379 ms | 8,592 ms |
| paper view kept per ledger head | 1 | 16 | 34.6 | 357 ms | 960 ms | 3,312 ms |
| answers encoded directly, lighter overview, shared market rows | 1 | 16 | 34.3 | 278 ms | 923 ms | 3,161 ms |
| the same | 1 | 1 | 32.2 | 8 ms | 99 ms | 205 ms |
| the same | 4 | 16 | 107.4 | 91 ms | 405 ms | 659 ms |

The first build read, decoded and re-hashed each person's whole ledger on
every page (0.9 s for 14,000 entries), and FastAPI's encoder walked every
answer in Python (135 ms for the 2.4 MB weather list against 22 ms for
`json.dumps`). One process then tops out near 35 requests a second: it is
CPU-bound, and the interpreter lock queues cheap requests behind large
ones (a trivial endpoint averaged 182 ms server-side under load). Four
processes on four cores gave 3.2 times the throughput; the client, one
Python process, was by then part of the limit. The server's own histogram
(`vp_http_seconds`) agreed with the client's counts exactly.

### Ingestion lag and reconnects

MEASURE_INGEST

### Venue rate limits observed

The client holds a token bucket per host (Gamma 10 a second with a burst of
20, CLOB 20 and 40, Data API 10 and 20), set from the venue's published
limits. Over the day no Polymarket host returned a 429: the dataset builds
made 7,351 CLOB and 320 Gamma requests (0.22 s and 0.33 s on average; one
connection error, retried), settlement 259 CLOB requests, discovery a
Gamma walk every ten minutes, reconciliation 300 Data API requests an
hour. Every one of these callers fetches one request at a time, far under
the buckets, so the day found no limit empirically; the buckets stay at
the documented values until a load that reaches them. Of the evidence
sources, GDELT answered 429 on every run and Open-Meteo 429 or a 30 s
timeout, from this container's shared address (below).

Settlement had made venue requests grow with the number of people: each
account asked about the same resolved markets (66 to 68 requests each at
12:37). The venue's record of a resolved market is now kept once for
everyone: at 13:37 the first two accounts, settling at the same moment,
made about 120 requests each, and the other thirteen one or two each,
taking 11 s instead of 139 s.

### Job start latency

| Kind | Jobs | p50 | p95 | max | Why |
| :--- | ---: | ---: | ---: | ---: | :--- |
| backtest, paper start | 4 | 0.01 s | 0.01 s | 0.01 s | `LISTEN vp_jobs` wakes a worker on insert |
| scheduler | 29 | 4.4 s | 4.9 s | 4.9 s | queued for the minute ahead; found by the five-second poll |
| evidence (before the pools were split) | 2 | 278 s | 440 s | 458 s | queued behind two dataset builds in one pool |
| evidence, reconcile (after) | 2 | 0.0 s | 0.0 s | 0.0 s | a pool of their own |
| paper cycle, 15 accounts firing at 13:07 | 16 | 88 s | 171 s | 180 s | two threads in one process share one core |

A cycle alone takes 6.1 s (the capture's forecasts memoised); the fifteen
took 205 s together, about 14 s of process time each, so one paper worker
process serves about 260 hourly accounts of the sample size. Threads do
not add CPU: a pool grows by processes.

### Cost per person per day

For a person with the sample paper account (four strategies over every
parsed market of three domains), from the hourly cycles and settlements
run here:

| Item | First day | Why |
| :--- | ---: | :--- |
| Model spending | $0 | the sample strategies are statistical; no model key in the container |
| Worker time | about 7 to 10 min | first cycle 7.5 s, later cycles 6 to 14 s, and a settlement of about 11 s, 24 of each a day |
| Ledger rows | about 58,000 (44 MB at 759 bytes a row) | 14,000 in the first cycle, then about 1,900 a cycle |
| Forecast rows | about 41,000 (25 MB at 619 bytes) | 11,500, then about 1,300 a cycle |

The ledger figure is after the change-only recording below; before it,
every cycle wrote every forecast again (about 14,000 entries a cycle, some
330,000 a person a day). It is still some 600 times the capacity model's
assumption of about a hundred entries a person a day, because every
person's sample account trades every market, and every one of these
accounts holds the same orders: flag F17 in the plan proposes one shared
sample account.

### Restore

`pg_dump -Fc` of the 271 MB database (555,000 rows, 7 paper accounts): 3.1 s,
a 29 MB file. `pg_restore -j 4` into an empty database: 1.9 s. Checked
after the restore: every table's row count equal to the source at the dump
(the quotes table alone had grown since, from the running service); all 7
paper ledgers then present, 99,721 entries, verified with the engine's
chain check in 1.9 s; the operator's audit chain intact. The object store
was not drilled: its datasets, histories and snapshots are rebuilt from the
venue, but its evidence captures and archived ledger months are not, so
the cloud bucket must be versioned (task 34).

### Storage of the shared market data

| Table | Rows | Size | Bytes a row |
| :--- | ---: | ---: | ---: |
| `quotes` (after the fixes, per day) | about 1.1 million | about 370 MB | 335 |
| `quotes` (as first built, per day) | 26 million | about 8.7 GB | 335 |
| `forecast_memo` (shared) | 128,000 | 47 MB | 388 |

The quote volume was measured over a clean nine minutes (13:37 to 13:46,
6,684 rows) after the last change: first outcomes only, every five minutes
where the top moved, every minute for held markets. Held markets were 755
of the 9,300, because the fifteen sample accounts hold almost every market
between them (flag F17). As first built, every token was written every
minute; the steps in between were every book with any event (17 million a
day), every moved top (12 million) and held markets on every move (another
5.5 million).

## Faults Found and Fixed While Measuring

Each is in the repository with a test.

| Found | Fix |
| :--- | :--- |
| The scheduler waited behind dataset builds in one pool; evidence waited 4.6 minutes | five pools: interactive, paper, platform, capture, data |
| A restart lost a dataset build's progress (and killed it after three restarts) | each history stored as fetched and never fetched again; 90 s to finish on stop |
| Weather's 146,000 settled markets made full histories impractical | the daily build takes the 2,000 most recent; an operator's refresh repeats the daily build |
| A paper cycle's cutoff was the moment the job ran, so no two accounts shared a memoised forecast | the cutoff is the capture's time |
| Every cycle wrote every forecast again; a ledger append was 1.8 ms and a cycle made 14,000 | forecasts recorded when new or moved by 0.005; a cycle appends in one batch; 55 s became 7.5 s |
| The paper view re-read the whole ledger on every request | kept per ledger head, for at most a minute |
| The overview carried every open position (1 MB) | it carries counts |
| The file cache of the dashboard grew without bound | bounded, keyed by path and loader |
| One web process topped out near 35 requests a second | `vp serve --workers`, metrics added across processes, cache writes safe to share |
| A backtest estimate parsed 146,000 markets (5.5 s) | a count per kind kept per dataset version |
| Estimates arriving out of order could show a stale answer | the page ignores all but the latest |
| Quotes: every token every minute, 26 million rows a day | first outcomes only, every five minutes when the top moved, every minute when held |
| Discovery rewrote all 9,300 markets every ten minutes, holding the interpreter while the sockets went unread; the venue closed two as slow consumers (code 1013) | only changed markets written, the rest marked seen in one statement; a 1,024-frame receive buffer |
| Ingestion lag included book pictures stamped days earlier | measured from change events only |
| Quote age measured how long a book had been quiet, so the alert would always fire | staleness is the silence of the token's socket |
| Resolution delay was not measured for the channel's own events | measured from the event's stamp |
| The first reconcile counted markets resolved a month before the service existed as a month late, holding the alert pending | counted from when the market was first tracked |
| Queue age counted jobs scheduled for later (negative ages) | only jobs ready to run; dataset builds alert on a six-hour scale |
| Settlement asked the venue for the same resolved market once per account | the venue's record is kept once for everyone |
| openfootball gives some scores as a bare pair | read |

## Observability

Prometheus (from `quay.io`) scraped all seven targets (four web processes
as one, five worker pools, the ingest service) and evaluated all ten alert
rules with no errors. Grafana's image was not pulled; its dashboard JSON
is provisioned but was not rendered here.

## What Was Not Measured

- Anything that needs the cloud host (flag F16): request latency from
  outside, lag over days, the region probe and terms review of flag F1,
  the managed database's point-in-time restore.
- Model costs: the container holds no Anthropic key, so batch and cache
  pricing were tested offline only; the first keyed run is still the
  first thing to do with a key (`CLAUDE.md`).
- Evidence from Open-Meteo and GDELT: both answered 429 or timed out from
  this container's shared address in every run, as Open-Meteo did in
  earlier phases; the collectors recorded the errors and the others
  captured. Their commercial terms (flag F9) are in `docs/evidence.md`.

## Stage A, Measured

The capacity model's stage-A column in `docs/scaling.md` § 11 is replaced
by these numbers.
