# The Platform

Phase 13 wraps the engine in everything needed to serve many people at
once. This page records what is built and why; the design it implements is
[product.md](product.md) for the shape and [scaling.md](scaling.md) for the
tenancy, storage and capacity decisions. The engine under `vp/` is
unchanged and knows nothing about any of it.

**Status.** Phase 13 is built and verified on the local stand-in
(2026-09-23): configuration, the principal, the tenancy boundary, the web
service with email sign-in, sessions and API tokens, storage in Postgres
and an object store, the job queue and its worker pools, the market-data
service, the evidence collectors, budgets and model keys, observability
and the operator's controls, all run together under Docker Compose. What
was measured is in `tests/reports/phase13_platform.md`. The cloud deploy
comes last (flag F16) and is the one part of the phase not done.

```bash
uv run vp db migrate          # as the owner: VP_MIGRATION_DATABASE_URL
uv run vp serve               # as vp_app: VP_DATABASE_URL, on :8000
```

In a web session the start-up hook starts Postgres, sets both URLs and
migrates, so `vp serve` works at once; sign-in links land in
`data/outbox/`. The whole platform (web, five worker pools, the
market-data service, Postgres, MinIO, and optionally Prometheus and
Grafana) runs from `deploy/compose.yaml`; see "The Local Stand-in" below.

## The Division

```ascii
vp/                 the engine: data roots, specs, cutoffs. No users, no HTTP.
vp/platform/        the platform: who is calling, where state lives, what it cost.
```

The first principle of the scaling design is that the engine never knows
who is calling, and the import direction enforces it: `vp/platform/` may
import the engine, and nothing in the engine may import the platform. That
is what lets one process serve one person today and a pool of workers
serve many later, and it is why per-user work is the platform's problem
rather than a parameter threaded through every engine function.

## Configuration

`vp.platform.config` is the only module that reads the environment. One
reader means the whole configuration surface fits on one page and a
missing setting fails at start rather than at the request that needs it.
`tests/test_config_gate.py` walks the package's syntax trees and fails if
a second reader appears.

Two engine knobs predate the platform and are listed as explicit
exceptions in that test: the per-host request spacing in `venues/_http.py`
and the kill-switch path in `live/controls.py`. They are command-line
conveniences rather than platform settings, and they fold into the config
module when the engine runs under the service. The test also checks that
each listed exception still reads the environment, so a stale entry cannot
quietly become a hole.

Two rules the types cannot express:

- **No secret has a default.** A missing `VP_DATABASE_URL` is a start-up
  error, never an empty string or a guess at localhost, because a default
  that happens to work in development is how a service reaches the wrong
  database in production.
- **Secrets do not print.** The database URL is excluded from the
  dataclass repr and reaches logs only through `redacted_database_url`, so
  a settings object in a traceback cannot leak a password.

| Variable | Required | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `VP_DATABASE_URL` | yes | none | the service's own connection, as `vp_app` |
| `VP_ENV` | no | `development` | `development`, `staging` or `production` |
| `VP_DATA_ROOT` | no | `data` | where the engine's Parquet files live |
| `VP_PUBLIC_URL` | in production | `http://127.0.0.1:8000` | the origin people reach the service at; must be `https://` in production |
| `VP_MIGRATION_DATABASE_URL` | for `vp db migrate` | none | the owner's connection string, for migrations only |
| `VP_MAIL` | no | `outbox` | where sign-in emails go; production refuses `outbox` |

`VP_DATABASE_URL` is the service's own connection and must be `vp_app`.
Keeping the owner's URL in a separate variable, used only by
`vp db migrate`, means the web process never holds a credential that
bypasses tenancy. Production refuses plain HTTP, because session cookies
must be `Secure`, and refuses the outbox, because a link written to a file
on the server reaches nobody; so no production configuration can load
until a mail provider is chosen (flag F3).

## The Principal

Every request, job and command carries a `Principal`: a subject, how it
authenticated, the workspace it is acting in, and the roles it holds.

`attributable` is the field that matters. It says whether the subject
names an actual person, it is derived from the authentication method at
construction, and it cannot be passed in, because a caller-settable flag
is a caller-settable lie. A session and an API token both name a person:
the first follows a verified email, the second is minted by someone signed
in. Anonymous does not. Any control that needs a named human, such as an
approval or an audit entry, checks `attributable` and refuses rather than
quoting a label as if it were a person.

Roles are held **within** a workspace, so there is no ambient authority: a
principal holding `owner` with no workspace may do nothing at all. The
exception is `operator`, which is held on the platform rather than in a
workspace, and which by construction reaches no workspace's data: it is
the role that reads costs, sets budgets and trips the platform halt.

| Role | Read | Write | Membership |
| :--- | :--- | :--- | :--- |
| `viewer` | yes | no | no |
| `editor` | yes | yes | no |
| `owner` | yes | yes | yes |
| `operator` | no workspace data at all | | |

## Tenancy

Everything a person owns belongs to a workspace, every tenant table
carries `workspace_id`, and Postgres row-level security answers every
query against the workspace set on the connection. The property this buys
is worth stating as the test does: **a query that forgets its filter
returns nothing, rather than someone else's data.** An unset workspace
matches no row, because a comparison against NULL is never true, so the
failure direction is closed.

Two database roles, and the guarantee depends on the difference:

- **The owner** runs migrations and nothing else. It owns the tables, so
  the policies do not apply to it. The service never connects as the
  owner: signing up, which must create a user, a workspace and a
  membership before any workspace context exists, happens inside five
  narrow database functions instead (see Sign-in and the Web Service).
- **`vp_app`** owns nothing and is subject to every policy. Everything
  else connects as this role. It must never be a superuser, which bypasses
  row-level security unconditionally; the test fixture asserts both.

The context is set with `set_config(..., true)`, local to the transaction,
so a pooled connection cannot carry one workspace into the next request.

### The savepoint hazard

This is the part that would have been a silent hole, and it is why
`connect` opens connections in autocommit mode.

A psycopg connection that is not in autocommit mode opens a transaction on
its first statement and holds it open. A `conn.transaction()` block on
such a connection is then a **savepoint inside that transaction**, not a
transaction of its own. Two consequences, neither of which raises
anything:

1. A workspace set with `set_config(..., true)` lives until the outer
   transaction ends, so the next request on that connection inherits it.
2. Writes sit uncommitted in the outer transaction and vanish when the
   connection closes.

Both were observed while building this: the migration runner left its
connection inside an open transaction, and the seeding that followed
appeared to succeed while committing nothing. The fix is structural rather
than careful coding. Connections are opened in autocommit mode, every unit
of work is an explicit transaction block, and both `migrate` and
`tenant_session` refuse a connection that is already inside a transaction
instead of quietly degrading to a savepoint.

### Migrations

Numbered SQL files applied in filename order, each in its own transaction,
each recorded with the SHA-256 of its bytes. A file that changes after it
has been applied is refused, because at that point the database and the
repository disagree about what the schema is and only one of them knows.
The ledger table is the platform's own bookkeeping and `vp_app` is
explicitly revoked from it.

`0001_foundation.sql` creates workspaces, users and memberships, their
policies, and the `vp_app` role. Role creation is idempotent and raises a
message naming the manual step if the connection may not create roles, as
on a managed host where the operator provisions roles out of band.

## Sign-in and the Web Service

`vp serve` runs one FastAPI application over the unchanged engine
(`vp/platform/web.py`). Every request resolves to a `Principal`, from a
session cookie or a bearer token, and every route that reads anything
requires one that names a person.

### Crossing the tenancy boundary, narrowly

Signing in has to create rows before any workspace exists, which the
policies refuse. The obvious fix, giving the web process the owner's
credentials for that step, would put a role that bypasses tenancy inside
the process most exposed to the internet. Instead, migration 0002 defines
five `SECURITY DEFINER` functions, which run as their owner and are the
only code that crosses the boundary:

| Function | Does |
| :--- | :--- |
| `vp_auth_request_sign_in` | records a sign-in token for an address, at most five per address per fifteen minutes |
| `vp_auth_sign_in` | exchanges an unused, unexpired token for a thirty-day session, creating the user and a personal workspace on first use |
| `vp_auth_resolve_session` | who a session belongs to, only while its membership exists |
| `vp_auth_end_session` | revokes a session |
| `vp_auth_resolve_token` | who an API token belongs to, only while its membership exists |

Two properties follow. **No function makes a session for a named user**:
the only way to one is a token that was sent to that user's address. And
**every limit is fixed in the function**, not passed in, so a caller cannot
lengthen a session or loosen the rate. Each function sets its own
`search_path` and uses no dynamic SQL. The sign-in and session tables have
row-level security with no policy and no grants to `vp_app`, so the
functions are the only way in. Removing a membership ends every session
and token in that workspace at once, because resolution joins on it.

### Secrets

The link's token, the session cookie and an API token are each 256 random
bits, given to the person once and stored as a SHA-256. A plain hash is
right here, not a slow password hash: these are random values, not
passwords a person chose, so there is nothing to guess. The session
cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` whenever the public URL
is HTTPS.

### Five rules the service enforces

1. **It connects only as a role row-level security binds.** At start it
   refuses a superuser, a role that may bypass row-level security, or the
   tables' owner. The tenancy suite proves isolation for `vp_app`; running
   as anything else would make it prove nothing.
2. **State changes come from its own pages.** A request that changes
   anything and is not bearer-authenticated must carry
   `Sec-Fetch-Site: same-origin` or a matching `Origin`. Without this,
   another site could post a form that signs a visitor out, or signs them
   into an account the attacker controls. Bearer requests are exempt,
   since browsers never add that header themselves.
3. **Opening a link does not sign in.** The emailed link opens a page with
   one button; only the button's `POST` spends the token. Mail scanners
   fetch every link in a message, and a link that signed in on `GET`
   would be spent before the person clicked.
4. **Secrets stay out of logs and referrers.** A log filter replaces every
   `token=` value in the access log, and `Referrer-Policy: same-origin`
   keeps the link's URL from being sent to any other site.
5. **Nothing personal stays in the browser's cache.** Every response
   except the fonts carries `Cache-Control: no-store`.

API tokens are managed only from a signed-in browser, so a leaked token
cannot mint more. A read token acts as a viewer; a write token acts with
its owner's role, never more.

### What the browser found

The request tests drive the service with `TestClient`, which sends
whatever headers a test chooses. Driving a real Chromium through the
whole flow found two faults they could not:

- **`Referrer-Policy: no-referrer` broke sign-in.** Under that policy
  Chromium sends `Origin: null` on the page's own form posts, which rule 2
  refused. The policy is now `same-origin`, and the check trusts
  `Sec-Fetch-Site: same-origin` first, which browsers always send and
  pages cannot forge.
- **The dashboard outlived sign-out.** Without a cache directive, Chromium
  served the dashboard page from its cache after sign-out without asking
  the server. The data calls were refused, so nothing leaked, but a shared
  computer showed a signed-in page. Rule 5 came from this.

The walk-through (sign-in page, emailed link, confirm button, dashboard
with the account panel, sign-out, and back to sign-in on revisiting)
passes, and the access log carries the token only as `[redacted]`.

### What the first gaps became

The four gaps this page listed on 2026-09-23 are closed: every view reads
the signed-in workspace's own rows (below); the page no longer speaks to
developers (the friendly interface, `docs/interface.md`); sign-in requests
are limited per client address as well as per email address
(`vp_rate_limit`, twenty an hour by default); and expired tokens and
sessions are swept by a scheduled job.

## Storage

Two stores, split by what the data is (`docs/scaling.md` § 4). Postgres
holds what belongs to a person or must be transactional: accounts,
ledgers, runs, forecasts, jobs, budgets, keys, the audit chain, and the
shared tables of the market-data service (tracked markets, quotes,
resolutions, the evidence index). An object store holds what is large and
immutable: dataset versions, price histories, snapshots, evidence
captures, run artifacts and archived ledger months. `LocalStore` (a
directory) and `S3Store` (MinIO locally, any S3 in the cloud) implement
one small protocol; `VP_STORE` picks.

The engine reads a data root, and the platform keeps one: `SharedRoot` is
a disk cache of the object store laid out exactly as the engine expects
(`markets/<domain>/resolved.parquet`, `histories/`, `snapshots/`). Keys
are immutable except each dataset's `LATEST` pointer, which is read
through, so a refresh fetches only what is new. A job gets a private
working root whose shared directories are links into the cache, so the
engine runs unchanged and never sees another workspace's files. Cache
writes go to a temporary name unique to the process and thread and are
renamed into place, because several web processes share one cache.

**The ledger in Postgres.** `PgLedger` stores the entries the file ledger
would write, hashed by the same function, one chain per paper account. An
append locks the account's head row, so two writers queue rather than
fork the chain. A paper cycle appends inside `PgLedger.batch()`: one
transaction, one lock and one pipelined insert for the whole cycle, chained
exactly as single appends are, and a cycle that fails writes nothing. An
export verifies offline with the engine's own `Ledger.verify`.

**Partitions and archives.** Ledger entries, forecasts and quotes are
partitioned by month (`vp_ensure_partitions`, run daily by a job, keeps two
months ahead). `vp admin archive <table> <month>` moves a closed month to
Parquet in the object store, reads it back to check every row is there,
and only then drops the partition; `PgLedger` reads archived months first,
so a chain still verifies from its first entry. `vp_app` holds no
privilege on any partition: naming a partition directly would bypass the
parent table's row-level security, so only the parent is reachable.

## Jobs

Everything that takes longer than a request is a job: a row in `jobs`
claimed with `FOR UPDATE SKIP LOCKED`, so any number of workers share one
queue. A job has a kind, a payload, an idempotency key, a priority
(interactive 50, scheduled 100, maintenance 200), a run-after time, a
lease renewed by a heartbeat thread, progress, a result, and the budget it
reserved. A failure is retried after $30 \cdot 2^{n-1}$ seconds; after the
last attempt the job is dead and waits for an operator. Cancelling sets a
flag the next heartbeat reads. Workers sleep on `LISTEN vp_jobs`, so a new
job starts within milliseconds; a job scheduled for later is found by a
five-second poll.

A job runs as a `Principal` with the `job` method and the id of the person
who asked, in their workspace, so it passes the same row-level security as
their requests. The platform's own jobs run as `system` and reach only
shared tables, through `SECURITY DEFINER` functions.

**The scheduler is a job.** Each run reaps expired leases, fires due
schedules (cron with an IANA time zone, via croniter) and queues itself for
the next minute under an idempotency key naming that minute, so however
many workers try, one scheduler runs per minute, and a lost one is
replaced a minute later. A person's paper trading is two schedules in
their own time zone: a cycle at seven past each hour and a settlement at
thirty-seven past.

**Pools.** A worker serves the kinds it is started with, so pools are
sized independently and long work never blocks short work. Compose runs
five: interactive (backtest, leakage), paper (paper cycle, settle),
platform (scheduler, partitions, sweep), capture (snapshot, evidence,
reconcile) and data (dataset builds, which run for hours). The split was
found, not planned: with the scheduler in the dataset pool it waited
behind a build, and evidence captures waited 4.6 minutes behind two.

**Work shared between people.** A paper cycle trades the latest capture
of the market-data service rather than taking its own, and forecasts at
the capture's time rather than the moment the job runs. That is when the
prices it trades against were seen, never later than now, so the cutoff
holds; and every account trading one capture asks the same question, so a
statistical forecast is computed once and read by everyone from
`forecast_memo`. Language-model forecasts are not memoised: a person's
prompt is private.

**A dataset build resumes.** Each price history goes to the object store
as it is fetched, and a build skips histories already stored (a settled
market's history does not change), so a build cut short by a restart or a
deploy carries on where it stopped. Weather has about 146,000 settled
markets, so its daily build fetches histories for the 2,000 that ended
most recently. On stop, a worker finishes its running jobs for up to its
lease; Compose gives it 90 seconds.

## The Market-Data Service

`vp ingest` holds one subscription to the venue for everyone
(`docs/scaling.md` § 5). Discovery walks Gamma's keyset pagination for
each domain every ten minutes and records tracked markets; markets it no
longer sees are marked closed. Every outcome token is subscribed on the
CLOB market WebSocket, 400 to a socket, with the custom-feature flag and a
`PING` every ten seconds; new tokens fill existing sockets before new ones
open, and a dropped socket reconnects with exponential backoff.

Books are kept in memory. Every five minutes each market whose best bid or
ask moved has its first outcome written to `quotes` (the second outcome
trades on the same book, mirrored, and a change of size alone writes
nothing); a market someone holds is written every minute its top moved.
Writing every token every minute, as first built, came to 26 million rows
a day for the 18,600 tokens tracked, and held markets written on every
move of their top another 5.5 million. Every
fifteen minutes each domain's snapshot is written from memory in the
engine's own format to the object store, and `NOTIFY vp_data` tells the
web processes to refresh their caches. Resolutions come from the
channel's `market_resolved` event, and an hourly reconcile asks the Data
API v2 about tracked markets past their end date with no resolution yet.
Closed is still not resolved: a label is written only from a resolution.

Freshness is measured two ways. The ingestion lag is the gap between the
venue's stamp on a change event and its receipt (a `book` message is a
picture stamped with the book's last change, so it is excluded). Staleness
is how long a token's socket has been silent: on a live socket the venue
sends every change and answers the ping, so a quiet book is current, and
the time since a book last changed (hours, for quiet markets) is not its
age.

## Evidence

Four collectors run hourly and write Parquet captures with their capture
time, indexed in `evidence_captures` (`docs/evidence.md` has the sources
and their terms): Open-Meteo forecasts for every city in the weather
markets (one multi-location request; geocoding cached), the openfootball
fixtures and results (CC0), the venue's own schedule of tracked markets,
and GDELT headlines per domain, queried from each domain's keywords so no
domain is hard-coded. Each collector fails alone and records why.

## Budgets and Model Keys

Each workspace has a monthly budget for model spending on the platform's
key ($5 by default, set per workspace by the operator). Starting a
backtest estimates its cost from the number of markets, reserves it under
an advisory lock (a start that would exceed the budget is refused with
402), and on completion replaces the reservation with the measured cost
from the model's token counts, cache reads and writes priced at 0.1 and
1.25 times input, and batch at half price. Spend is recorded per model
call with the forecaster, domain, model, tokens and who paid.

A person may store their own Anthropic key. It is sealed with AES-GCM
under a data key that is itself sealed under `VP_MASTER_KEY` (envelope
encryption; the master key stands in for the cloud key-management service
until the deploy), is shown only as its last four characters, and can be
replaced or deleted at any time. Calls on an own key are recorded as
`own_key` and do not count against the budget. Every client, the
platform's or a person's, passes through one limiter per key across all
processes: advisory-lock slots, four by default, so a pool of workers
cannot exceed the provider's concurrency.

## Observability and Operations

Each process keeps Prometheus metrics: requests by route and status and
their latency; jobs finished, their duration and start latency; queue depth
and oldest ready age by kind; venue requests by host and status (a 429 is
visible); the feed's reconnects, tokens, lag and staleness; resolution
delay; spend; ledger append latency. The web serves them at `/metrics`
behind `VP_METRICS_TOKEN`, and workers and the ingest service on their own
ports. `vp serve --workers N` runs several web processes; their metrics
are kept in files and added up at each scrape. Traces are OpenTelemetry
spans per request, job and venue call, sent nowhere, to the log or to an
OTLP collector (`VP_TELEMETRY`). `deploy/alerts.yml` holds the alerts,
each with an entry in `docs/runbook.md`, and `deploy/grafana` a
dashboard.

The operator works from the command line: `vp jobs` (list, show, retry,
drain, stats) and `vp admin` (halt and resume the platform, pause a
workspace, budgets, costs, a data refresh, archive, the audit chain).
While the platform is halted no job is claimed; a paused workspace's jobs
wait, its schedules move on without queueing (a missed hourly cycle is
skipped, not saved up), and its waiting jobs do not age the queue the
backlog alert watches. Every operator action is an entry in a hash-chained audit log that
names the operator.

## The Local Stand-in

`deploy/compose.yaml` runs the platform from one image: Postgres 16, MinIO,
a setup job that migrates and creates the bucket, the web service (four
processes), the five worker pools, the market-data service, and with
`--profile observability` Prometheus and Grafana. `deploy/compose.proxy.yaml`
adapts it to a sandbox whose traffic must pass a proxy (host networking,
the proxy's certificate). `.github/workflows/ci.yml` runs the checks and
the tests against a Postgres service and builds the image; it deploys
nothing. The cloud deploy of task 34 is the last step of the phase.

## Running the Database Tests

The suite stays offline by default; the database tests skip unless both
connection strings are set. In a web session the start-up hook sets them,
so `uv run pytest -q` runs everything. The first must own the tables, the second must
be `vp_app`. Pointing both at the same role would make every assertion
pass for the wrong reason, so the fixture checks they differ and that the
second is not a superuser.

```bash
createdb vp_dev
VP_TEST_DATABASE_URL='postgresql:///vp_dev?host=/var/run/postgresql&user=postgres' \
VP_TEST_APP_DATABASE_URL='postgresql:///vp_dev?host=/var/run/postgresql&user=vp_app' \
uv run pytest -q
```

## Measured

**Venue reachability (flag F1), 2026-09-21, from the development
container.** All three hosts answered: Gamma search, the CLOB markets
endpoint and the Data API each returned HTTP 200 in under 0.6 s. This is
the technical half of F1 only, and it was measured from this container,
**not** from the region the platform will run in. The check that matters
is the same probe from the deployed region, together with the reading of
the venue's terms on automated access, data storage and commercial use;
both are tasks of this phase and neither is done.

**The stand-in, 2026-09-23.** The whole platform ran under Docker Compose
for an afternoon with live venue data: the walk-through of the phase's
"done when" in Chromium, request latency under load, ingestion lag,
staleness and reconnects, venue requests, job start latency, cost per
person-day, a restore drill, and the storage of the shared market data.
The figures, and the 23 faults the measuring found and fixed, are in
`tests/reports/phase13_platform.md`; the stage-A column of
[scaling.md](scaling.md) § 11 now holds them.
