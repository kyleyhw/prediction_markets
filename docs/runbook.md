# Runbook

One entry per alert in `deploy/alerts.yml`, in the order an operator is
likely to meet them. Each says what the alert means, what to look at, and
what to do. The operator's commands are `vp jobs` and `vp admin`, which
connect as the database owner (`VP_MIGRATION_DATABASE_URL`); everything they
change is recorded in the audit chain (`vp admin audit`).

The first move for anything that could make the platform wrong rather than
slow (a venue outage, a bad deploy, runaway spending) is the platform halt:
`vp admin halt --reason "..."`. While it is set no worker claims a job and
no model call is made; `vp admin resume` clears it. One workspace can be
paused with `vp admin pause <workspace> --reason "..."`.

## Quotes stale

`vp_quote_age_p99_seconds > 60` for five minutes: for the slowest percent
of tokens, the socket carrying them has heard nothing from the venue for
over a minute, so the books the snapshots and paper cycles read may be that
old. The objective is under 60 s at the 99th percentile. A quiet market is
not stale: on a live socket the venue sends every change and answers the
ten-second `PING`, so the age is the socket's silence, not the time since
a book last changed (which runs to hours for quiet markets).

- Is `vp ingest` running? `docker compose ps ingest`, then its log.
- Reconnects (`vp_ws_reconnects_total`) rising means the channel is
  dropping; see the next entry.
- A socket that stays connected but silent (the maximum climbing while
  reconnects are flat) is a half-open connection: restart `vp ingest`.
- If the feed cannot recover, halt the platform so paper cycles do not
  trade stale prices, and resume once quotes are fresh.

## Market feed reconnecting

More than five reconnects in ten minutes. The service reconnects on its own
with backoff up to a minute; repeated drops usually mean the venue or the
network is unwell. Check the ingest log for the close reason. If the venue
has changed its channel (a new subscription format, a moved URL), the fix is
in `vp/platform/ingest.py` and the probe in `docs/platform.md`.

A close with code 1013, "slow consumer: send buffer full", is ours: the
service did not read fast enough and the venue gave up on the socket. It
was seen on 2026-09-23 when discovery rewrote every market while the host
was saturated. Check the ingest process's CPU (`docker stats`); the
service needs a core of its own, and its periodic work (discovery,
snapshots, quote flushes) must stay small, because it shares the
interpreter with the sockets.

## Resolutions late

The 90th percentile delay from the venue resolving a market to our record
is over fifteen minutes. The hourly `reconcile` job catches anything the
live `market_resolved` event missed, so a delay near an hour means the
events are not arriving. Check `vp jobs list --kind reconcile` for failures,
and the ingest log for `market_resolved` events. Settlement asks the venue
itself for any market recorded as resolved, so a late record delays labels
but never makes one wrong.

## Queue backlog

A job kind has waited more than ten minutes to start, or a dataset build
more than six hours (`DatasetBacklog`: builds run for hours, and the next
waits its turn). `vp jobs stats` shows depth and age by kind and state; a
job scheduled for later is not counted as waiting.

- Is the pool for that kind running? Compose runs five: interactive
  (backtest, leakage), paper (paper_cycle, settle), platform (scheduler,
  partitions, sweep), capture (snapshot, evidence, reconcile) and data
  (dataset).
- Is the kind drained (`vp jobs drain`)? Undrain it with `vp jobs undrain`.
- Is the platform halted, or the workspace paused? `vp admin halts`.
- Otherwise the pool is too small for the load: raise its `--concurrency`
  or run another copy; claiming is safe with any number of workers.

## Dead jobs

A job failed every attempt. `vp jobs list --state dead` and `vp jobs show
<id>` give the error. Fix the cause, then `vp jobs retry <id>`. A dead
`paper_cycle` whose error says the ledger chain is broken must not be
retried until the chain is examined: the refusal is deliberate.

## Venue rate limited

The venue answered 429. Every process spaces its requests with a token
bucket per host (`VENUE_RATES` in `vp/platform/run.py`); a 429 means the
limits are set above what the venue now allows, or several deployments
share an address. Lower the rate for that host and redeploy. Record the new
limit in the Phase 13 report's table.

## Server errors

More than one request in a hundred is answered with a 5xx. The web log
carries the traceback (the response only says "internal error"). A database
that refuses connections, an object store that is down, or a migration that
has not been applied are the usual causes; `/readyz` checks the database.

## Slow requests

The 95th percentile request takes over a second. The market views read
Parquet from the local cache: a cold cache after a restart is slow for its
first requests. If it persists, look at `vp_http_seconds` by route.

## Spend rising

Model spend passed $20 in an hour. Budgets stop each workspace at its
monthly limit, so this is many workspaces at once, or one on its own key
(which does not count against the platform). `vp admin costs` shows the
month by workspace, forecaster, domain and model. If it is not expected,
halt the platform, then lower budgets with `vp admin budget`.

## Ledger chain broken

Found by the daily whole-chain check (`vp admin verify-ledgers`, the
`verify-ledgers` service in Compose), not by an alert. A trading cycle
checks only the entries after its account's last verified checkpoint, so a
change to an entry before the checkpoint is caught here, within a day. The
check pauses the workspace (`vp admin halts` shows the reason, naming the
account and the first bad entry) and records its run in the audit chain.

- Export the account (`/api/paper/export` as the person, or the rows as the
  owner) and keep it before touching anything.
- Compare the entry with the archived months and the backups: the backup
  from before the change holds the entry as written.
- Nothing rewrites a ledger. If the entry was changed by a fault of ours,
  say so to the person, restore the account from the backup, and resume the
  workspace (`vp admin resume --workspace <id>`). If it cannot be restored,
  the account stays closed and a new one is opened; the old chain is kept
  as evidence.

## Restoring the database

The drill (Phase 21 report) restored a dump of the 10,000-person stand-in
into a fresh database and checked it. The order, with the times measured:

1. Halt the platform (`vp admin halt --reason "restore"`) so no job writes
   during the restore.
2. Restore the managed database's point-in-time copy, or on the stand-in
   `pg_restore --jobs 4 -d vp <dump>` into an empty database.
3. `vp db migrate` (applies nothing on a current dump; says so).
4. `vp admin verify-ledgers` and `vp admin audit`: every chain from its
   first entry, and the audit chain.
5. Point the services at it, `vp admin resume`, and watch `QueueBacklog`
   drain.

Object storage is versioned and is not restored with the database; runs
whose files are newer than the restored rows are orphans, which is
harmless.

## Abuse

The limits in place, each exercised in the Phase 21 report: five sign-in links
per email address in fifteen minutes, twenty sign-in requests an hour per
network address, 120 requests a minute per
API token, six account exports an hour, each workspace's monthly model
budget, and the operator's pause of one workspace. A workspace that floods
the queue is paused (`vp admin pause <workspace> --reason "..."`); its
queued jobs wait and its running ones finish. Its person is told why by
email before it is resumed or closed.
