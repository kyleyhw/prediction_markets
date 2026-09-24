# Phase 21 Test Report: Scale Proof and Operations

Date: 2026-09-24. Environment: Python 3.14.7 via `uv 0.12.18`, Postgres 16,
`vp serve` with four processes, on one 4-core development container.

The cloud deploy is deferred (flag F16), so "staging" here is the local
stand-in. The database, the web service and the load generator shared the
same four cores. Every figure is therefore a lower bound on what separate
hosts would do, and nothing here measures the network between hosts.

The Phase 13 stand-in's own Postgres volume was brought up again for its
real paper record and job history.

## Purpose

The capacity model in `docs/scaling.md` § 11 was a set of estimates. This
phase measured it with synthetic workspaces at the scale of 10,000 people.
The million-person column is extrapolated from those measurements and says
so.

The aim was to find the first component to miss its objective and fix it.
Measuring found seven faults, each a cost that grew with the size of the
platform rather than the size of the request. All seven are fixed, and
each fix was measured again.

The phase also made the platform operable:

- a daily check of every ledger chain;
- a restore drill;
- the abuse controls exercised;
- export and deletion of a person, timed at scale;
- cost per person-day shown to the operator.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |
| `pytest -q` | 353 passed (350 before the phase) | 30 s |

New and extended tests:

- `test_platform_ledger.py`:
  - a checkpoint verifies and replays only what follows it;
  - a change before the checkpoint is caught only by the daily check,
    which pauses the workspace once and records itself;
  - the daily check follows a chain across an archived month into
    Postgres.
- `test_platform_db.py`: every column a person is found by is indexed.
- `test_platform_work.py`: an account exports whole, holding none of its
  secrets and nothing of another person's, then deletes.
- `test_platform_console.py`: `vp admin unit-costs` prints.

## The Load Generator (task 105)

`vp/platform/loadgen.py` seeds people, workspaces, paper accounts and a
day of valid ledger chains by `COPY`, one hundred entries a person (the
capacity model's rate). Everything it writes is tagged and removable.

| Seed | People | Ledger entries | Time |
| :--- | ---: | ---: | ---: |
| 100 people | 100 | 10,000 | 0.14 s |
| 10,000 people | 10,000 | 1,000,000 | 17 s |
| August cohort (for the archive) | 2,000 | 200,000 | 3 s |

The probes measure one component each:

- ledger appends from separate processes;
- a trading cycle's chain check;
- job claims under a deep queue;
- the rate limiter;
- the web's views under concurrency, with 500 sessions of the 10,000
  people;
- export and deletion of one person.

The first append probe used threads and measured Python's own lock: 969
appends a second from one thread, 489 from sixteen. Processes measure the
database.

## Measured at 10,000 People

### Ledger appends

These are single appends on distinct accounts, as settlements write them,
with 1,000,000 entries already in the table.

| Writers | Appends a second | p50 | p95 | p99 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 808 | 1.1 ms | 1.8 ms | 2.5 ms |
| 4 | 3,160 | 1.1 ms | 2.0 ms | 2.7 ms |
| 8 | 3,035 | 2.3 ms | 4.3 ms | 6.5 ms |
| 16 | 2,911 | 4.8 ms | 9.6 ms | 13.1 ms |

Four writers saturate four cores. The capacity model's 10,000 people
write a million entries a day, about 12 a second on average, or 0.4% of
the measured rate. This table is with the indexes added below; before
them, four writers made 3,195 a second, so the indexes cost about 1%.

### A trading cycle's chain check

Each cycle verified the account's whole chain and replayed it to rebuild
positions.

| Chain | Verify | Replay | With a checkpoint (after the first) |
| ---: | ---: | ---: | ---: |
| 100 entries (a day) | 0.002 s | 0.002 s | 0.001 s + 0.001 s |
| 3,650 (a year at 10 a day) | 0.054 s | 0.031 s | 0.001 s + 0.001 s |
| 36,500 (a year at 100 a day) | 0.68 s | 0.43 s | 0.001 s + 0.001 s |

**Fault 1.** A cycle's cost grew with the account's age: 1.1 s at a year.
At 30,000 hourly accounts that is nine cores, and growing. The fix is a
verified checkpoint per account (migration 0026). It holds the hash of a
verified entry and the replayed accounts at that point. It advances only
inside a verification that passed, every 200 entries. A cycle now checks
and replays only the entries after it: 0.001 s at any length. The first
full verification of a year's chain takes 0.81 s, once.

A change to an entry before a checkpoint is no longer seen by the cycle.
So the whole chain of every ledger is now verified daily, from its first
entry, archived months included (below).

### Job claims

Claimers take a job and mark it done until the queue is empty. The queued
jobs are of a kind no worker runs.

| Queued | Claimers | Before: claims a second, p95 | After |
| ---: | ---: | :--- | :--- |
| 3,000 | 4 | 915, 5.8 ms | 1,810, 2.1 ms |
| 30,000 | 8 | **261, 96 ms** | 1,663, 5.3 ms |
| 30,000 | 16 | — | 1,513, 11.4 ms |
| 300,000 | 8 | — | 1,822, 4.9 ms |

**Fault 2, and the first component to miss its objective.** With
`kind = any (kinds)`, the planner scanned every queued job and sorted them
on disk for each claim: 30 ms a claim at 30,000 queued, O(n). The million-
person platform needs about 833 claims a second (section 1M below), and a
deep queue gave 261. Job start latency, whose objective is 30 s for
interactive work, would have grown without bound in a backlog.

The claim now takes the head of each kind from an index in exactly the
claim's order, and the best head across the kinds wins (migration 0027).
Priority across kinds is unchanged. A claim takes 0.1 ms at 30,000 queued,
and throughput no longer depends on depth: 1,822 a second with 300,000
queued.

### The rate limiter

`vp_rate_limit` counts API-token requests, sign-in requests and exports in
Postgres.

| Writers | Keys | Checks a second | p95 |
| ---: | ---: | ---: | ---: |
| 1 | 10,000 | 1,066 | 1.7 ms |
| 8 | 10,000 | 1,990 | 6.7 ms |
| 8 | 100 | 1,785 | 7.6 ms |

**Fault 3.** Every check also deleted the windows older than a day, and
no index led with the window, so the delete scanned the table. At a day of
windows for 1,000 tokens (1.44 million rows) each check took 148 ms. It
takes 1.1 ms with an index (migration 0028).

### The web

Four `vp serve` processes answered 500 signed-in people of the 10,000,
each asking for seven of the dashboard's views at random: `/auth/me`,
overview, paper, strategies, notifications, risk, leaderboards.

| Concurrent clients | Requests a second | p50 | p95 | p99 | Errors |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 621 | 5.9 ms | 11 ms | 14 ms | 0 |
| 16 | 844 | 17.5 ms | 35 ms | 46 ms | 0 |
| 32 | 815 | 35 ms | 76 ms | 101 ms | 0 |
| 64 | 778 | 75 ms | 156 ms | 208 ms | 0 |
| 128 | 741 | 158 ms | 296 ms | 382 ms | 0 |

The objective is a p95 under 500 ms for cached views. It holds at 128
concurrent clients, with the load generator on the same four cores.

At 16 clients each request cost 2.8 ms of web CPU and 1.8 ms of Postgres
CPU. Over 30 s and 23,000 requests the web processes used 64 CPU-seconds
and Postgres 41.

**Fault 4.** Before the fix every request took at least 48 ms, however
fast the server was. With several processes uvicorn rebuilds the
listening socket in each worker. asyncio then does not set `TCP_NODELAY`,
so a response waited on the client's delayed acknowledgement over a
kept-alive connection. `vp serve --workers N` now binds the socket itself
with `TCP_NODELAY` and hands it to the workers. Browsers set the option on
their side, which hid the stall from the Phase 13 walk-through. It would
have cost every API client and the load test 40 ms a request.

### Export and deletion of one person

| Ledger | Export before | Export after | File | Delete before | Delete after |
| :--- | ---: | ---: | ---: | ---: | ---: |
| 100 entries | 0.30 s | 0.03 to 0.10 s | 74 KB | 0.37 s | 0.015 s |
| 36,500 entries | 3.1 s | 3.5 s | 27 MB | 0.42 s | 0.035 s |

**Fault 5.** There was no export, although the privacy notice promised
"every record the service holds for you as one file". Only the paper
ledger could be downloaded. `docs/platform.md` even said "Export was
already there". `vp_export_account` (migration 0029) mirrors the
deletion:

- the same tables, found by the same columns;
- the person's own rows where a table has a `user_id`;
- the workspace's rows where it has only a `workspace_id`;
- no hashes of secrets, encrypted keys, lease tokens or pairing codes.

The file carries the archived ledger months too. Settings has a
"Download my data" button, and exports are limited to six an hour.

**Fault 6.** Deleting or exporting a person scanned every table without
an index on the column it filters by. That includes every paper ledger on
the platform, which is a million rows here and grows by a hundred million
a day at a million people, and the whole job history. Migration 0030
indexes all 37 such columns, and a test fails if a new table misses one.
The 36,500-entry export is dominated by writing 27 MB of JSON.

### The daily whole-chain check

`vp admin verify-ledgers` runs daily as the `verify-ledgers` service in
Compose. When it finds a broken chain it:

- pauses the workspace holding it, unless the workspace is already paused;
- records its run in the audit chain;
- is answered by a runbook entry.

| Ledgers | Where | Time |
| :--- | :--- | ---: |
| 10,008 (1,000,000 entries) | all in Postgres | 20 s |
| 12,004, with 2,000 chains archived to object storage (one month, 200,000 rows) | before the fix: one read of every archived month for each account | 0.228 s an account, **46 minutes** |
| the same | after: each month read once | 24 s |
| 18, the Phase 13 stand-in's real ledgers | | 18 s; the 15 known broken chains found, all already paused, no new pause |

**Fault 7.** The check read every archived month again for each account,
which is O(accounts × months). It would have passed a day at about thirty
archived months. It now reads each month once. It keeps the verified head
of every account and continues each chain from it into the next month,
then into Postgres.

### Restore drill (task 109)

The 10,000-person database (1.8 GB) was dumped and restored into an empty
database. Every ledger and the audit chain were verified on the copy.

| Step | Time |
| :--- | ---: |
| `pg_dump -Fd --jobs 4` (94 MB) | 7.8 s |
| `pg_restore --jobs 4` into an empty database | 11.7 s |
| `vp db migrate` ("up to date") | 0.8 s |
| `vp admin verify-ledgers` (10,004 ledgers, none broken) | 22.8 s |
| `vp admin audit` (verified) | 0.8 s |

A verified copy took 44 s. The order is in `docs/runbook.md`,
"Restoring the database". A managed database's point-in-time restore
replaces the first two steps, and its time waits on the deploy.

### Abuse controls exercised (task 109)

Against the running service:

| Control | Tried | Result |
| :--- | :--- | :--- |
| Sign-in links per email address (5 in 15 minutes) | 6 requests | 5 links sent. Every answer was the same 200, so nothing reveals whether a link went. |
| Sign-in requests per network address (20 an hour) | 25 requests | 5 refused with 429 |
| Requests per API token (120 a minute) | 125 requests | 120 answered, 5 refused with 429 |
| Account exports (6 an hour) | 7 | 6 answered, 1 refused with 429 |
| The operator's pause of a workspace | a job queued for it | not claimed while paused, claimed after resuming |

The model budget stops a workspace at its monthly limit. It is exercised
by `test_a_model_backtest_needs_a_key_and_fits_the_budget` and by the
Phase 13 budget tests. There is no key to spend against for real (task
60).

## Cost per Person-Day (task 108)

`vp admin unit-costs --days N` gives the operator cost per person-day by
component from the live system:

- job time by kind, with work that has no workspace shown as shared;
- model spend paid by the platform;
- database storage.

Prices are the operator's to set. The defaults ($0.03 per vCPU-hour,
$0.25 per GB-month) stand until the host's invoice replaces them. On the
Phase 13 stand-in's real day (24 people, 5.3 hours of operation, before
the shared sample account):

| Component | Runs | Dollars | Per person-day |
| :--- | ---: | ---: | ---: |
| shared: dataset builds | 2 | 0.0279 | 0.00039 |
| paper cycles | 58 | 0.0238 | 0.00033 |
| settlements | 35 | 0.0106 | 0.00015 |
| shared: reconcile | 6 | 0.0092 | 0.00013 |
| shared: evidence | 7 | 0.0020 | 0.00003 |
| backtests | 5 | 0.0007 | 0.00001 |
| database storage (830 MB) | | 0.0218 | 0.00030 |
| **total, before web replicas and model spend** | | | **0.0013** |

From the measured units, at 10,000 people with the capacity model's
workload:

| Component | Unit measured | Per person-day |
| :--- | :--- | ---: |
| Paper cycles, hourly | about 260 accounts an hour a worker process (Phase 13, an upper bound: the sample account wrote 40,000 entries a day) | ≤ $0.003 |
| Ledger storage | 1,430 bytes an entry with indexes; 100 a day; a month hot before archiving | $0.00004 |
| Web requests | 4.6 ms of CPU a request (web and database) | $0.00001 at 200 requests |
| Web replicas and the database host, fixed | three 4-core replicas at the capacity model's peak | about $0.001 |
| Shared work (datasets, evidence, ingest, reconcile) | about 1.5 cores continuously, per market, not per person | $0.0001 |
| **Platform, without models** | | **about $0.004** |
| Model spend, the person's budget | $5 a month at most | up to $0.17 |

The platform's own cost is under half a cent a person-day. The model
budget is up to forty times that. **Budget and tier defaults stay as
decided** (the $5 budget, the cheap tier for breadth, F8): the budget,
not the infrastructure, sets what a person costs. The platform's own
forecasts are per market, not per person. They wait on the key to be
measured.

## Stage B, Decided on the Measurements (task 106)

| Piece | Decision | Why, and the trigger |
| :--- | :--- | :--- |
| Web, workers and ingest as separate services | **built** (Phase 13) | Compose runs the web, five worker pools, the ingest and now the daily check as separate services from one image |
| Monthly partitions archived with chain hashes | **built** (Phase 13), and its check fixed here | 46 minutes to 24 s for the daily check over an archived month |
| Redis for limits and cache | **not adopted** | The Postgres limiter does 2,000 checks a second at 1 ms each since fault 3. It counts only tokens, sign-in and exports, not every page. The views are cached per process by ledger head. Trigger: limiter p95 above 10 ms, or more than 1,500 checks a second sustained. |
| A read replica | **not built** | Each web request costs the primary 1.8 ms of CPU, so a 4-core primary at 60% serves about 1,300 requests a second besides its writes. The capacity model's peak for 10,000 people (2,500 a second) would need one; a page that refreshes every thirty seconds would not. Trigger: the primary's CPU above 60% at the peak. Adding it is a deploy change plus routing the dashboard's reads to a second pool; writes, and anything read straight after one, stay on the primary. |

## The Queue and the Stream (task 107)

**The Postgres queue stays.** Claims take 1.8 ms, and claim throughput
(1,822 a second) no longer depends on the depth of the queue. That is
twice what a million people need (833).

The trigger to move it to a dedicated system behind the same `Queue`
interface is either of:

- a claim p95 above 50 ms;
- demand above 1,000 claims a second.

A deep queue's dead rows are vacuumed. Claim latency with 300,000 queued
(4.9 ms p95) shows no bloat effect at that depth.

**No stream.** The market-data service writes about 1.1 million quote
rows a day (Phase 13), 13 a second, and publishes changes through Postgres
notifications. The trigger is sustained quote writes above 2,000 a
second, which ten times the markets would not reach.

## A Million People, Extrapolated

| Component | Needed at a million | Measured on 4 shared cores | Reading |
| :--- | :--- | :--- | :--- |
| Ledger appends | 100 M a day: 1,160 a second on average, about 3,500 at the peak | 3,160 a second | One primary is at its limit. With 143 GB a day of hot ledger, this is the stage-C trigger: shard by workspace. |
| Job claims | about 833 a second | 1,822 a second | Fits (fault 2 fixed). A dedicated queue follows the triggers above. |
| A cycle's chain check | 1 M accounts hourly | 0.002 s each | 0.6 cores (fault 1 fixed; it was 300 cores at a year) |
| Daily chain check | 1 M ledgers | 20 s for 10,000 | About 35 minutes in one process, parallel by shard |
| Web | the capacity model's 250,000 a second at the peak | 4.6 ms of CPU a request | About 1,200 cores at the peak. The capacity model's estimate of five requests a second for each person online is likely high; measure real use before buying for it. |
| Delete or export one person | anytime | 0.015 s, 0.03 s | Indexed (faults 5 and 6), so it no longer grows with the platform |

The step to a million is the ledger's volume, as `docs/scaling.md` § 11
predicted. The measurements add the web's CPU at the model's peak.

## The Growth Path's Triggers, With Current Values

| Stage move | Trigger | Current value |
| :--- | :--- | :--- |
| A to B | Page p95 over 500 ms | 35 ms at 16 concurrent, 296 ms at 128 |
| A to B | Queue age | Claim p95 5 ms; job start 10 ms (Phase 13) |
| A to B | Sustained CPU above 60% | Not measurable on the shared container; waits on the deploy |
| B to C | Ledger append p95 | 2.0 ms at 4 writers, 9.6 ms at 16 |
| B to C | Replica lag | No replica |
| B to C | Queue table bloat | None seen at 300,000 queued |

## Operations

- **Runbook** (`docs/runbook.md`): new entries for a broken ledger chain
  (found by the daily check, not an alert), restoring the database, and
  abuse.
- **On-call and a status page** wait for the deploy and for people who
  would notice. A status page on the same host would go down with it, so
  it belongs with the deploy's provider.
- **Retention:** sessions expire after 30 days and sign-in links after 15
  minutes, and finished jobs are removed after 90 days. The daily `sweep`
  enforces this, as the privacy notice says. Rate-limit windows go after a
  day. Old ledger months move to object storage.
- **Self-hosting for developers** (F9) is documented in
  `docs/platform.md`: the same image and Compose file, the developer's own
  keys and acceptance of each source's terms, and no shared archive.
  Publishing the image waits for the deploy.

## Found and Fixed

| Fault | Fix |
| :--- | :--- |
| A cycle's chain check grew with the account's age: 1.1 s at a year | Verified checkpoints: 0.002 s at any length, plus a daily whole-chain check |
| Each job claim sorted the whole queue: 261 claims a second at 30,000 queued | Head of each kind from an ordered index: 1,822 a second at 300,000 queued |
| Each rate-limit check scanned a day of windows: 148 ms at 1,000 tokens | Index on the window: 1.1 ms |
| Kept-alive requests stalled 40 ms on delayed acknowledgements with several web processes | The listening socket bound with `TCP_NODELAY` |
| The export the privacy notice promised did not exist, and the platform docs said it did | `vp_export_account`, the Settings button, the docs corrected |
| Deleting a person scanned every ledger and the job history | 37 indexes and a test that keeps new tables indexed |
| The daily check read every archived month once for each account: 46 minutes | Each month read once: 24 s |
| The new `verify-ledgers` service was missing from the proxy overlay, so it could not reach the database on this machine | Added |
| A test left a job queued that the next run's worker claimed before its own | The test cancels it |

## Not Done

- **The deploy (F16).** Staging on a real host, request latency from
  outside, sustained CPU, a managed restore, replica lag and the host's
  invoice for the cost figures all wait on it. It must come before any
  real user.
- **Metrics under load came from the probes.** Prometheus was not scraped
  during the load runs. The ingest-side metrics (quote freshness,
  resolution delay) are Phase 13's; the ingest is per market, so the
  number of people does not change them.
- **A limit on signed-in page requests per network address** is in the
  design (§ 9) but not built. Tokens, sign-in and exports are limited.
  The edge proxy at the deploy is the place for it: a check in Postgres
  would add about half again to a request's database cost.
- **The platform's model spend per person-day** needs the key (task 60).

## Amendment, 2026-09-24: the Whole Platform on the Stand-In, Again

After Phases 21 to 23, the full platform was run again under Docker Compose
on the Phase 13 stand-in's own volumes. This is still the simulation of
the cloud host (F16): the same image for every process, Postgres 16 and
MinIO for the managed services, and now the documentation site served
from a static folder (`site`, behind the `docs` profile).

| Check | Result |
| :--- | :--- |
| Image build | 59 s; code-only rebuilds a few seconds |
| Setup on the Phase 13 data | migrations 0014 to 0030 applied in one pass to real data; `/readyz` ready |
| Services | 11 running: web (4 processes), five worker pools, ingest, the daily `verify-ledgers`, Postgres, MinIO, the site |
| The market feed | 8,895 markets, 17,700 tokens on 45 sockets; 99% of quotes under 5.5 s old (objective 60 s) |
| The daily ledger check | 18 ledgers from their first entry; the 15 chains known broken since Phase 13, all already paused, so no new pause |
| A new person in Chromium | signed in with the consent tick in 1.3 s; a weather backtest of 2,000 markets queued from the page ran in the interactive pool in 8 to 14 s; the account's export downloaded (10 KB); Risk, Signals and Settings opened |
| Restore drill on the stand-in (890 MB) | dump 13.6 s (86 MB), restore 9.2 s, migrations and every ledger 9.0 s, audit chain verified in 1.6 s: a checked copy in about 33 s |
| The site | every page served, `llms.txt` included |

Found and fixed by this run:

| Fault | Fix |
| :--- | :--- |
| A backtest started from the page paid no fees and said so ("This run assumed no fees"), though paper trading and strategy backtests charge each market's own fee (F5) | Page backtests charge each market's own fee by default; the run's sizing line says "each market's own" |
| The backtest form opened on a domain with no dataset, so a newcomer's first sight was "this domain's data has not arrived yet" | Domains with data come first; the others say "(no data yet)" |
| A finished job still showed its first progress message ("Done · 0 of 2000 markets") | Finished jobs show no progress message |

Not reached in this run: the stand-in's store held only the weather
dataset, since its Phase 13 builds of the other domains never finished.
The data worker picked them up again (the reaper retried their expired
leases) and builds them in the background. As the runbook says, they take
hours.
