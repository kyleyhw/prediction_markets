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
