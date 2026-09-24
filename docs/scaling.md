# Scaling to Many Users

vibe-predict is to serve many people at once: a few at first, then, if it
earns them, thousands or more. This page is the design that makes that
possible without rebuilding, and the capacity model that says what "many"
costs. It applies from the first hosted release (Phase 13) and is proven
under load in Phase 21; until then its numbers are estimates, and each is
marked as such. The product design it serves is [product.md](product.md);
the engine it scales is unchanged.

## 1. Principles

1. **The engine never knows who is calling.** `vp/` takes data roots, specs
   and cutoffs; the platform adds identity, storage, queues and money around
   it. This is what lets one process serve one user today and a pool of
   workers serve a million later.
2. **Shared work is computed once; per-user work is metered.** Market data,
   evidence, resolved datasets, platform forecasts and signal benches are
   public goods. Strategies, paper accounts, sessions, memory, budgets and
   mandates are private. The line between them is the main scaling decision.
3. **Strategies are data, not code.** Nothing a user writes is executed;
   the engine interprets a spec. There is therefore no sandbox to scale, no
   arbitrary CPU to bound, and every run is reproducible from its manifest.
4. **Background work goes through one queue.** Every non-interactive action
   is a job with a kind, an idempotency key, a priority and a budget, so
   capacity is added by adding workers, and nothing runs twice by accident.
5. **One subscription to the venue, however many users.** A single
   ingestion service holds the WebSocket subscriptions and the request
   budget; users read from our copy. Ten thousand users must not become ten
   thousand pollers.
6. **Measure before believing.** Each capacity number below has an
   assumption beside it and is replaced by a measurement in the Phase 21
   report.

## 2. Shared and Per-User Work

| Shared (computed once, stored once) | Per user or workspace |
| :--- | :--- |
| Market catalogue, quotes, books, histories, snapshots | Strategies and their versions |
| Resolution states and labels | Paper accounts and hash-chained ledgers |
| Evidence archive (forecast runs, results, fixtures, headlines) | Research sessions, messages, memory |
| Resolved datasets, versioned and immutable | Backtest runs made from a private spec |
| Platform forecasts (baselines, signals, committees) at standard cutoffs | Forecasts made with a private prompt or belief |
| Signal bench results, the public benchmark | Budgets, settings, tokens, channels |
| Domain packs, committee presets, playbooks (platform copies) | Overrides of any of those |
| Fee schedules per market over time | Mandates, session keys, live ledgers |

**Forecast memoisation.** A forecast is a pure function of (market, cutoff,
forecaster configuration, evidence version). Its key is the SHA-256 of that
tuple; the value is stored once and reused by every strategy and every user
whose spec asks for it. A committee run on a popular match at the 24-hour
cutoff is paid for once. Private prompts get private keys and private bills.

**Dataset versions.** A resolved dataset is written as an immutable version
(a directory of Parquet files plus a manifest with row counts and hashes),
and a backtest names the version it read. Two users backtesting the same
spec on the same version get the same run card from the cache; a new version
invalidates nothing, it is simply newer.

## 3. Tenancy and Identity

- **Principal.** Every request carries a principal: `subject`, `auth_method`,
  `attributable` (true only when an identity provider named a person, never
  settable by a caller), `workspace`, `roles`. Vibe-Trading's model has the
  same fields as placeholders; here they are real from the first release.
- **Workspaces.** Every user gets a personal workspace; a team is a workspace
  with more members. Everything per-user in section 2 belongs to a workspace,
  and every table carries `workspace_id`. Roles are owner, editor, viewer,
  and an operator role for the platform.
- **Isolation.** Postgres row-level security policies on every per-workspace
  table, set from the request principal, so a query that forgets a filter
  returns nothing rather than someone else's data. A tenancy test suite
  attempts every cross-workspace read and write.
- **Sign-in.** Email magic link first, OpenID Connect later; sessions in
  HTTP-only cookies; API tokens hashed at rest, scoped (read, write,
  workspace) and revocable; the single-use ticket pattern for browser event
  streams so a long-lived token never sits in a URL.
- **Attribution.** Every write records the principal; ledger entries carry
  it inside the hash chain.

## 4. Storage

- **Postgres** holds the control plane and per-workspace state: users,
  workspaces, memberships, strategies and versions, runs and their manifests,
  forecasts (with the memo key), paper accounts, ledger entries, jobs,
  budgets and spend, settings, tokens, channels, audit. Managed, with
  point-in-time recovery and a tested restore.
- **Per-account hash chains** in Postgres: appending to a ledger takes an
  advisory lock on the account, reads the last hash, writes the entry. The
  chain is the same format `vp/paper/ledger.py` writes, so `Ledger.verify`
  runs unchanged over an export, and a user can download and verify their
  own ledger offline.
- **Object storage** (S3-compatible) holds everything columnar: dataset
  versions, price histories, snapshots, the evidence archive, backtest
  artifacts, ledger archives, run cards. Paths are content-addressed where the
  content is immutable.
- **DuckDB** reads Parquet in object storage for analytics (benches, Research
  Lab studies, the overview counts) without loading it into Postgres. A local
  disk cache keeps hot files near the workers.
- **Partitioning and retention.** Ledger entries and forecasts are
  partitioned by month; closed months are exported to Parquet in object
  storage with their chain hashes and dropped from the hot database after a
  retention window. Quotes coalesced to one row per minute per market are
  kept hot for thirty days and archived after.
- **Migrations** are versioned and run as a job before a deploy completes;
  no schema change is made by hand.

## 5. The Market-Data Service

One service family, horizontally sharded by token id when needed, does all
talking to the venue.

- **Discovery.** Gamma keyset pagination (`after_cursor`, introduced April
  2026) replaces the end-date walk the data layer uses today; new markets
  also arrive on the WebSocket `new_market` event.
- **Quotes and books.** The CLOB market channel
  (`wss://ws-subscriptions-clob.polymarket.com/ws/market`) with dynamic
  subscribe and unsubscribe, `book`, `price_change`, `last_trade_price` and
  `tick_size_change` events, the `best_bid_ask` and `market_resolved` events
  behind the custom-feature flag, and a `PING` every ten seconds. Books are
  kept in memory per token. Quotes are written for each market's first
  outcome only (the second trades on the same book, mirrored), every five
  minutes for a market whose best bid or ask moved, and every minute for
  markets a strategy holds; a book whose top has not moved writes nothing,
  and the quote at a moment is the latest row at or before it.
- **Resolutions.** The `market_resolved` event, the Data API v2
  `/v2/resolutions` endpoint, and the CLOB `winner` flag, in that order of
  speed and the reverse order of authority; a sweep reconciles anything a
  stream missed. The closed-is-not-resolved invariant is unchanged.
- **Snapshots.** The existing Parquet snapshot writer runs from the in-memory
  state on a schedule, so `vp snapshot`, the backtests and the paper loop see
  the same files they see today.
- **Fan-out.** Consumers subscribe to changes through Postgres `LISTEN` and
  `NOTIFY` in the first stage and a stream (Redis Streams or NATS) when the
  number of consumers or the message rate outgrows it. No consumer talks to
  the venue.
- **Request budget.** The service owns one token bucket per venue host, set
  from measured limits (the venue publishes order-endpoint limits; read
  limits are measured, not assumed, and recorded in the Phase 13 report),
  with backoff on throttling. The current per-host spacing of 0.35 s is the
  starting value.
- **Freshness.** A service-level objective on the age of the newest quote
  for any tracked market (target: under 60 s at the 99th percentile) and on
  the delay from resolution to label (target: under 15 min), both measured
  and alerted.

## 6. Jobs and Workers

- **Queue.** A `jobs` table in Postgres claimed with `SELECT ... FOR UPDATE
  SKIP LOCKED`: kind, payload, idempotency key (unique), priority, run-after
  time, attempts, lease, heartbeat, status, progress, result, workspace and
  budget reservation. No second system to operate in the first stage.
- **Kinds and pools.** Ingest, evidence capture, dataset build, forecast
  (LLM and statistical separately, since one is network-bound and the other
  CPU-bound), backtest, paper cycle, settlement, delivery, admin. Each kind
  has its own worker pool sized independently; a slow LLM queue never delays
  a settlement.
- **Semantics.** At-least-once delivery with idempotent handlers; retries
  with exponential backoff and a dead-letter state; leases with heartbeats so
  a killed worker's job is re-claimed; progress events the page can show;
  cancellation by flag.
- **Schedules.** Cron entries with IANA timezones for snapshots, paper
  cycles, settlements, dataset and evidence refreshes, briefs and reports;
  the scheduler is itself a job that enqueues jobs, so it scales with the
  rest.
- **Growth.** Measured in Phase 21: 1,822 claims a second with 300,000
  jobs queued, p95 under 5 ms, once each claim read its kind's head from
  an ordered index (it had sorted the whole queue: 261 a second at 30,000
  queued). A million people need about 833. When claim p95 passes 50 ms
  or demand passes 1,000 a second, the same job model moves to Redis or a
  workflow engine (Temporal or equivalent) behind the same interface; the
  handlers do not change.

## 7. LLM Cost and Concurrency

The LLM is the only expensive thing per unit of work, so it gets the most
controls.

- **Tiers of platform forecasts.** Statistical forecasters and signals run on
  every parsed market at every standard cutoff for free. LLM forecasts run on
  markets that some strategy selects, at the cutoffs it needs, with a
  cheaper model for breadth and the expensive model or a committee on
  demand; both are memoised by key.
- **Prompt caching.** The system prompt, the domain pack and the tool
  definitions are a stable prefix and are cached.
- **Batch API for backtests.** A backtest's forecasts are offline and
  order-independent, so they go through the provider's batch endpoint at
  half the price when the user accepts the delay; interactive previews use
  the live endpoint on a sample.
- **Budgets.** Each workspace has a monthly budget; a run shows its estimated
  cost (from token estimates and the memo hit rate) before it starts,
  reserves it, and debits actual usage on completion. Users may add their own
  key, stored under envelope encryption in the key-management service, which
  lifts their budget and moves the bill.
- **Concurrency.** One limiter per provider key across all workers (a
  token bucket in Postgres in the first stage, Redis later), with backoff on
  rate-limit responses; queue priority favours interactive work.
- **Attribution.** Every forecast records model, tokens, cache hits and
  dollars; the overview shows spend by workspace, forecaster and domain.

## 8. Backtests and Paper Trading at Scale

- **Backtests** are deterministic given (spec version, dataset version, cutoff
  rule, seed). The run card is cached by that key. CPU per run is seconds for
  statistical forecasters (the Phase 9 report measured 1 to 15 s for 400
  markets); LLM-based runs are bounded by budget and sample size, not CPU.
- **Paper cycles** are batched by market: one forecast per (market, cutoff,
  forecaster) serves every strategy that needs it; sizing and ordering are
  per strategy against the shared book state; one ledger append per order
  and per settlement. Settlement is event-driven from `market_resolved` with
  an hourly reconciliation sweep.
- **Fills** in paper trading are simulated against the book we hold; at
  scale the same simulated fill is reused across strategies that order the
  same side at the same instant, with resting size shared (first come, first
  filled) so that paper accounts cannot collectively "buy" more than the
  book showed.

## 9. API and Web Tier

Stateless FastAPI replicas behind a load balancer; static assets on a CDN
with long cache lifetimes and hashed names; JSON responses with ETags;
pagination on every list; response byte budgets on artifact reads; per-user
and per-IP rate limits (token buckets, Postgres first, Redis later); server-
sent events for progress with ticket authentication; WebSockets only if a
page needs sub-second updates. The build-free front end (product.md) means
no build farm either.

## 10. Observability and Operations

- **Telemetry.** OpenTelemetry traces across request, job and venue call;
  metrics for queue depth and age per kind, job latency, LLM spend and
  cache hit rate, WebSocket lag and reconnects, quote freshness, resolution
  delay, ledger append latency, error rates; structured logs with the
  redaction filter the security design already requires.
- **SLOs.** Quote freshness and resolution delay (section 5); page p95 under
  500 ms for cached views; job start latency under 30 s for interactive
  kinds; monthly availability target stated in the Phase 13 report.
- **Alerts and runbooks.** One runbook per alert; an on-call rota once there
  are users who would notice.
- **Kill switches.** A platform halt (a row, not a file: no worker runs
  jobs, no LLM call is made, no order is prepared while it is set); a
  workspace halt; the user's own halts (Phase 22). Each is a ledger entry.
- **Backups and recovery.** Point-in-time recovery for Postgres, versioned
  object storage, a restore drill on a schedule, a documented recovery time.
- **Secrets.** In the host's secret store or a key-management service, never
  in the image or the repository; detect-secrets already guards commits.
- **Deploy.** One image with three entry points (web, worker, ingest); CI
  runs the tests and deploys `master`; a staging environment receives every
  deploy first; migrations run as a job; rollbacks are a redeploy of the
  previous image.

## 11. Capacity Model

Estimates, to be replaced by Phase 21 measurements. Assumptions: three to
ten domains; 3,000 open markets tracked at a time (up to 10,000 with more
domains); each user runs three strategies selecting fifty markets a day
between them, placing twenty paper orders and generating about a hundred
ledger entries a day; five percent of users are online at the peak hour;
platform LLM forecasts cost $0.01 (cheap tier, cached) to $0.05 (committee)
each and are memoised, so their cost is per market, not per user.

| Quantity | 100 users | 10,000 users | 1,000,000 users |
| :--- | ---: | ---: | ---: |
| Quote rows per day (one per market per minute, 10% of minutes change) | 0.4 M | 0.4 M | 1.4 M (10k markets) |
| Platform forecasts per day (3 cutoffs, statistical) | 9,000 | 9,000 | 30,000 |
| Platform LLM forecasts per day (selected markets only) | 300 | 3,000 | 30,000 |
| Platform LLM cost per day at $0.01 to $0.05 | $3 to $15 | $30 to $150 | $300 to $1,500 |
| Ledger entries per day | 10,000 | 1 M | 100 M |
| Ledger growth per year (hot, before archiving) | 3.7 M rows | 365 M rows | 36.5 B rows |
| Backtests per day (one per user) at 15 s CPU | 0.4 CPU-h | 42 CPU-h | 4,200 CPU-h |
| Peak concurrent users / requests per second | 5 / 25 | 500 / 2,500 | 50,000 / 250,000 |
| Postgres | one small instance | one instance plus a replica, partitioned | sharded by workspace |
| Workers | one process each of web, worker, ingest | pools of 2 to 10 per kind | autoscaled pools |

Reading it: up to ten thousand users the design in sections 3 to 10 runs on
one managed Postgres with a read replica, one object store, a handful of
worker processes and two or three web replicas, and the platform's own LLM
bill is small because forecasts are shared. The per-user LLM bill is the
users' budgets. The step to a million users is a step in the ledger volume
(a hundred million appends a day), which is why the ledger is partitioned
and archived from the start and why workspaces are the sharding key; the
engine, the queue model and the market-data service do not change shape.

### Stage A, measured (2026-09-23)

Phase 13 measured stage A on the local stand-in: one 4-core machine
running Postgres, MinIO, the web service, five worker pools and the
market-data service together (`tests/reports/phase13_platform.md`). The
figures replace the estimates above for this stage; the larger columns
wait for Phase 21.

| Quantity | Measured | Against the estimate |
| :--- | :--- | :--- |
| Markets and tokens tracked | 9,300 markets, 18,600 tokens on 47 sockets | three times the 3,000 assumed, for three domains |
| Ingestion lag (venue stamp to receipt) | 95% within 250 ms, 99.5% within 500 ms | |
| Book staleness (socket silence), 99th percentile | 8 s | objective 60 s |
| Quote rows per day | about 1.1 M (26 M as first built) | 0.4 M |
| Requests a second, one web process | about 35, CPU-bound | |
| Requests a second, four processes | 107 at 16 concurrent, p50 91 ms, p95 405 ms | 25 at the peak for 100 people |
| Job start, interactive | 10 ms | |
| Paper cycle, sample account | 6 s alone, about 14 s of process time under load; about 260 hourly accounts a worker process | |
| Ledger entries per person per day, sample account | about 40,000 | about 100 (flag F17) |
| Backtest, 146,000 weather markets, two strategies | 8 to 25 s | 15 s CPU |
| Restore of the database (271 MB) | 3.1 s dump, 1.9 s restore | |

Reading it: the design holds at this stage with two corrections. Web
processes, not threads, carry the load (one per core). And the sample
paper account, as built, gives every person the whole market's ledger:
at a thousand people it would write about 40 million ledger rows a day,
which is why flag F17 proposes one shared sample account. Without it the
per-person figures are what a person's own strategies select.

### 10,000 people, measured (2026-09-24)

Phase 21 seeded 10,000 people with a day of ledger each (a million
entries) on the same kind of machine: one 4-core container running the
database, four web processes and the load generator together
(`tests/reports/phase21_scale.md`). The million-person column is
extrapolated from these.

| Quantity | Measured | At a million, extrapolated |
| :--- | :--- | :--- |
| Ledger appends | 3,160 a second at p95 2 ms (4 writers) | about 3,500 a second at the peak: one primary's limit, so sharding by workspace (stage C) |
| Ledger size | 1,430 bytes an entry with indexes | 143 GB a day hot, archived monthly |
| A cycle's chain check | 0.002 s at any length, from a verified checkpoint | 0.6 cores for hourly cycles |
| Job claims | 1,822 a second at 300,000 queued | 833 needed |
| Web, cached views | 844 requests a second at p95 35 ms (16 clients), 741 at p95 296 ms (128); 2.8 ms web and 1.8 ms database CPU a request | about 1,200 cores at the model's peak of 250,000 a second, which is probably high |
| Deleting one person | 0.015 s | the same: indexed |
| Daily check of every chain | 20 s for 10,000 ledgers | about 35 minutes, parallel by shard |
| Restore to a verified copy | 44 s for 1.8 GB | waits on the managed database |
| Platform cost a person-day, without models | about $0.004 | |

Measuring found seven costs that grew with the platform, not the request,
and fixed them (the report lists them). The first to miss an objective
was the job queue, whose claims were O(queue length).

## 12. Growth Path

| Stage | Users | Shape | Trigger to move on |
| :--- | ---: | :--- | :--- |
| A | to about 1,000 | one image, three processes on one host; managed Postgres; object storage | p95 latency, queue age or CPU sustained above targets |
| B | to about 50,000 | web, worker and ingest as separate services; Redis for limits and cache; read replica; monthly partitions archived | ledger append latency, replica lag, queue table bloat |
| C | beyond | autoscaled worker pools; Postgres sharded by workspace (Citus or per-shard databases); a dedicated stream; multi-region reads | measured, not scheduled |

The move from A to B changes deployment, not code; from B to C changes the
data layer behind interfaces that Phase 13 fixes (a `Store` for per-workspace
state, a `Queue`, a `MarketState` reader).

## 13. Security at Scale

Tenancy isolation is tested, not assumed (section 3). Session keys and
user-supplied API keys are stored under envelope encryption with a
key-management service and are never logged; live execution has three
independent halts (section 10 and Phase 22). Abuse controls are budgets,
rate limits, sign-up friction and the operator's pause. Live execution is
gated by jurisdiction; paper trading is not real money and is not. Personal
data is exportable and deletable per workspace. An external security review
precedes public live execution.

## 14. What Is Measured Before It Is Believed

Phase 21 ran synthetic workspaces at 100 and 10,000 people on the local
stand-in, found the first component to miss its objective (the job
queue), fixed it and six other costs that grew with the platform, and
published the numbers in `tests/reports/phase21_scale.md`. The million-
person column is extrapolated. What needs a real host (latency from
outside, sustained CPU, replica lag, the invoice) waits on the deploy
(F16), and until then those rows of this page remain a design.
