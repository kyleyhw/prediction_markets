# vibe-predict: project context for Claude sessions

Read this first; it carries the state a fresh session does not have. The
user's global conventions apply on top of it. Key project-specific ones: work
directly on `master` (no branches unless experimenting), commit and push
often, no Claude or Anthropic attribution anywhere, ask before starting each
plan phase, and keep code minimal with full reasoning in docs.

## What this is

A platform on which people implement their own forecasting strategies for
binary Polymarket contracts through conversation with an LLM, in three
domains (CS2 esports, weather, English Premier League). The platform is
the aim, not any particular edge: it supplies the data, the cutoff-safe
evidence, the scoring, the backtest, paper trading, a dashboard and,
behind an agreed security design, live execution, so that a strategy
described in conversation can be built, scored honestly against the market
and run. The baseline results it reports (no baseline beats the market)
are the benchmark it offers, not a target it has failed. Polymarket is the
only venue for the foreseeable future; Kalshi is deferred. The LLM
forecaster is the central component, in the spirit of HKUDS/Vibe-Trading,
which was reviewed and partly ported (see `docs/provenance.md`, `NOTICE`).

The original `prediction_markets` project is archived unchanged under
`archive/prediction_markets/` and excluded from tooling. Do not delete it.

## Where things are

- `PROJECT_PLAN.md`: phases 1–5 are the archived project; 6–12 are the
  engine and dashboard; 13–23 are the hosted platform for many users
  (`docs/product.md`, `docs/scaling.md`), rewritten in detail on
  2026-09-18 with a decisions table at the end. Status tags are kept
  current; update them as tasks finish.
- `README.md`, `docs/index.md`: entry points. `docs/architecture.md` has the
  data flow and design decisions; then one page per phase:
  `data_layer.md`, `forecasters.md`, `scoring.md`, `sizing.md`,
  `paper_trading.md`, `security.md`, `ui.md`; and the platform design
  pages `product.md`, `scaling.md`, `site.md`, plus `vibe_trading.md`, the
  full review of the reference implementation with the capability mapping
  and the non-infringement rules.
- `vp/platform/`: the hosted platform around the engine (Phase 13, built
  on the local stand-in): `config.py` (the only reader of the
  environment), `principal.py`, `db.py` (migrations, `tenant_session`),
  `auth.py`, `mail.py`, `web.py` (the FastAPI service), `views.py` (the
  dashboard over a workspace's rows), `storage.py` (object store and the
  shared disk cache), `ledger.py` and `archive.py` (the paper ledger in
  Postgres), `jobs.py` and `handlers.py` (the queue and what it runs),
  `ingest.py` (the market-data service), `evidence.py`, `budgets.py`,
  `llmops.py` (keys and the model limiter), `observe.py`, `audit.py`,
  `ops.py` and `console.py` (`vp jobs`, `vp admin`), `run.py` (process
  entry points) and `migrations/*.sql`. Reasoning in `docs/platform.md`,
  alerts in `docs/runbook.md`, deploy files in `deploy/`. The engine must
  never import it (`tests/test_platform_boundary.py`); `vp/cli.py`, the
  composition root, imports it only inside its platform commands.
- `vp/sources/`: evidence sources shared by the command line and the
  platform's collectors (Open-Meteo runs and ensembles, stations,
  openfootball) and the backfill (Phase 17, `docs/evidence.md`).
- `vp/signals/`: the signal library, gates, bench, blends, committees and
  the benchmark's arithmetic (Phase 16, `docs/signals.md`).
- `vp/`: the engine. `venues/polymarket.py` (read-only client with the
  closed-is-not-resolved evidence ladder), `domains/` (cs2, weather, epl),
  `markets/` (record, source, Parquet store, dataset, snapshot),
  `forecast/` (evidence, baselines, Elo, LLM, registry), `backtest/`
  (scoring, sizing, simulator, runner, bankroll), `paper/` (ledger, loop,
  leakage), `live/` (safety layer only), `ui/` (read-only dashboard),
  `cli.py` (`vp build-dataset`, `vp snapshot`, `vp backtest`, `vp paper`,
  `vp ui`).
- `tests/`: offline tests only; `tests/reports/` has a report per phase with
  runtimes. `data/` is git-ignored.

## State at handoff (2026-09-19)

Phases 6 to 10 and 12 are complete. Phase 11 is superseded: on
2026-09-19 the user decided live execution is hosted only (so strategies
trade while the user's computer is closed) and built last, as Phase 22;
the safety layer in `vp/live/` stays and is reused, and `docs/security.md`
is the base for the design's version 2. Nothing in the repository can sign
or send an order. Each phase has a report in `tests/reports/` with what was
measured live.

Direction set on 2026-09-18 (`docs/product.md`): the product becomes a
hosted web app for people with no technical background, with no terminal
for users; developers and the operator keep the command line; it must
scale to many users (`docs/scaling.md`). The plan's Phases 13–23 were
rewritten that day after a full review of Vibe-Trading
(`docs/vibe_trading.md`, which also records its collaborative tools and
the non-infringement rules): 13 platform foundation, 14 friendly for
everyone, 15 research sessions and the strategy spec, 16 signal library,
committees and benchmark, 17 evidence archive and new domains, 18
collaboration and delivery, 19 shadow forecaster, 20 portfolio, risk and
the promotion protocol, 21 scale
proof, 22 hosted live execution (built last), 23 the documentation site (default "paper" style in `docs/site.md`,
alternatives to trial later). Phase 13 **started on 2026-09-21**; the configuration module, the
principal, the database foundation and the tenancy boundary are built and
tested (`docs/platform.md`), and the web service, sign-in, jobs, the
market-data service, deploy, budgets and observability are not.
On 2026-09-23 the web service with email sign-in, sessions, API tokens
and the dashboard behind sign-in landed and was verified in a real
browser. The session-start hook now starts Postgres
(`.claude/hooks/postgres.sh`), exports `VP_DATABASE_URL` (as `vp_app`),
`VP_MIGRATION_DATABASE_URL` (owner) and the two test URLs, and runs
`vp db migrate`, so `uv run pytest -q` runs the database tests too and
`uv run vp serve` works at once; sign-in links land in `data/outbox/`.
Outside a web session, database-backed tests skip unless the test URLs
are set; `docs/platform.md` says how. Also found that day: the
`*.html` rule in `.gitignore` had silently kept the dashboard page out
of git since it was written; it is now excepted and committed. On
2026-09-23 the user deferred the Fly.io account and the cloud deploy to
the end (flag F16): build and verify on a local stand-in (Postgres 16, an
S3-compatible store such as MinIO, the same image under Docker Compose).
The deploy must happen before Phase 21 at the latest and before any real
user. Everything runs on the development machine until then, collectors
included, and the evidence gaps between sessions are accepted. **Build
order (2026-09-23): the interface first**: tasks 28, 29 and 37, then the
Phase 14 interface tasks 39 to 47 pulled forward (the user's request is
their go-ahead), then the rest of Phase 13, with the deploy, 48, 49 and
the host measurements last. See the build-order block at the top of
Phases 13 to 23 in the plan. Also on 2026-09-23: paper orders now pay each
market's own taker fee, read from `feeSchedule` (F5, task 37), and the
friendly interface landed (tasks 39 to 47, `docs/interface.md`): a
build-free ES-module app in `vp/ui/static/app/` served by both `vp serve`
and `vp ui`, with Simple and Detailed reading levels, a guided start,
home, market cards, Learn and per-person settings (migration 0003); every
word in `app/locales/en.json`; zero axe-core violations at WCAG 2.2 AA.
What is left of step 2: a real screen-reader pass (47), the settings that
wait on later tasks (46). **Phase 13 was built the same day** (step 3) and
verified on the local stand-in: storage, jobs and five worker pools, the
market-data service live on about 18,600 tokens, evidence collectors,
budgets and own keys, observability, `vp admin`, Compose and CI; a browser
walk-through of the "done when" and the measurements are in
`tests/reports/phase13_platform.md`. Measuring found and fixed 23
faults (the report lists them). Open from it: **flag F17** (every sample
paper account is the same account; about 40,000 ledger rows a person a
day; the owner accepted a shared sample account, built the same day
in `vp/platform/sample.py`), the
fifteen stand-in test workspaces paused with broken ledger chains (from a
negative-zero fault, now fixed; they stay until a general cleanup of
test data, by the owner's decision), and the
cloud deploy (task 34, F16), after which the host measurements, 48 and 49
follow. Open-Meteo and GDELT answer 429 or time out from this container.
**Phase 15 was built the same day** under the owner's goal "implement
the next three phases" (`docs/strategies.md` first, decisions as proposed):
the spec (`vp/strategy/`), props parsed against the venue's own
`sportsMarketType` (the record now stores `market_type` and the resolution
`description`), domain packs (`vp/domains/packs/`), the compiler, preview,
research assistant with the number gate and loop guards, manifests and run
cards, strategy versions and paper accounts per version (migration 0017),
memory, the evals harness (`vp strategy eval`, `vp admin evals`) and the
pages (`#describe`, `#strategy`, `#research`); report in
`tests/reports/phase15_strategies.md`. **Task 60 is blocked on an API
key**: nothing model-backed has run for real; the first keyed session runs
`vp strategy eval --live` and an LLM strategy backtest. Strategy backtests
charge each market's stated fee, or the published 5% where a record states
none. **Phase 16 was built the same day** (`docs/signals.md`): the
signal contract, gates and checklist (`vp signals check`), eleven signals
(`vp/signals/`), the bench against the market (`vp signals bench`),
blends, committees (built, not evaluated: no key), contamination
accounting (no model cutoff recorded yet, so every model result counts as
contaminated), and the weekly benchmark with sealed forecasts (migration
0018, `vp/platform/signals.py`, the Signals page). Nothing is alive on any
domain; report in `tests/reports/phase16_signals.md`. Week 2026-W39 is
frozen on the stand-in and waits for its questions to resolve.
**Phase 17 followed the same evening** (`docs/evidence.md`,
`docs/domains.md`): the archive reader with manifests and point-in-time
visibility (`vp/forecast/archive.py`), weather forecasts as issued at each
market's own station (`vp/sources/`, `vp evidence weather-runs`, 53
stations backfilled from 2024-10), the `nwp_forecast` signal (the first
weather signal level with the market a day out; its backtest is promising
and unproven, see the report), football results as dated facts with a
derived table, archive tools for the LLM forecaster, fee-aware Phase 9
baselines (report amended, one earlier claim corrected), the venue's v2
history and resolution shapes fixed, and the domain kit with a boundary
test (`tests/test_domain_boundary.py`: no code outside `vp/domains/` names
a domain). Report in `tests/reports/phase17_evidence.md`. Waiting: the
Open-Meteo paid plan (F9), an LPDB key for Liquipedia, a licensed
football feed, GDELT (429 here). Earlier,
the decisions each phase needed were taken on 2026-09-19 as proposed
(Fly.io with Amsterdam as the first region, magic-link sign-in, quarter
Kelly with a 5% cap and a 0.03 minimum edge, fees shown, session keys for
live execution, the "paper" site style) and are recorded with fifteen
flags at the end of the plan; the gating ones are F1 (confirm the host
region is not geoblocked by the venue before deploying), F5 (paper trading
charges no fees today and must), F9 (evidence sources' commercial terms),
F12 (a session key can trade the whole balance). F11 was resolved the
same day: the repository is MIT-licensed (`LICENSE`, `pyproject.toml`). The
owner also set the rule that venue access must be lawful under the venue's
terms and the law of the host's and users' places, never merely
unblocked (F1), that paper trading must use the backtest's fee model (F5,
task 37), and that self-hosting is not the users' path (F9, task 108).
F15 is resolved: hosted live execution only, built last. Phase 15 still gets `docs/strategies.md` before any
code, and the user wants sizing defaults a prompt can override and
per-strategy P&L views. The domains will open up beyond CS2, weather and
EPL; do not hard-code the three anywhere new, and the repository
description no longer names them.

What exists, in order of the data flow: the Polymarket client and data
layer (`vp/venues`, `vp/markets`, `vp/domains`); forecasters behind a
cutoff-bounded `Evidence` object (`vp/forecast`: market price, constant,
climatology, Elo, and the LLM forecaster on the official Anthropic SDK);
scoring, sizing, the fill simulator and `vp backtest` (`vp/backtest`,
which also writes `results.json` per run); paper trading on a hash-chained
ledger with settlement and the leakage check (`vp/paper`); the live safety
layer (`vp/live`); and the interface (`vp ui` locally, `vp serve` behind
sign-in: ES modules without a build step, the "paper" palette, vendored
Instrument Sans and JetBrains Mono, charts drawn in the page with a
table of their numbers, a glossary behind every term in Detailed mode;
see `docs/interface.md`).

Things a future session should know:

- The LLM forecaster has never been run against the API: the container
  holds no credentials. `LLMForecaster()` builds a client from the
  environment, so the first keyed run needs only the key, and
  `vp backtest --forecasters market llm --max-markets 50` on a domain is
  the first thing to do with it. The cost per forecast is printed.
- Fees: the venue sets each market's taker rate ($C \cdot r \cdot
  p(1-p)$; zero before spring 2026, then 3% or 5%), datasets built since
  2026-09-23 carry it, and `vp backtest --market-fees` charges it; the
  Phase 9 report has the fee-aware amendment (task 77).
- Live baseline results (Phase 9 report): no baseline beats the market
  (weather climatology skill −0.19, EPL Elo −0.02, CS2 Elo −0.12). Edge is
  not the goal; these are the benchmark a user's strategy is measured
  against.
- Evidence comes from the resolved dataset itself and, since Phase 17, the
  archive under `<root>/evidence/`: `vp evidence weather-runs` backfills
  point-in-time forecasts at every station (about 12 minutes; the free
  Open-Meteo hosts answer 429 from this container at times, and the
  command resumes), `vp evidence football --season 2025-26` the results,
  `vp evidence ensemble` needs a snapshot of open weather markets first
  (about an hour with books). Read `docs/evidence.md` on the fetch-latency
  rule before touching visibility.
- Known follow-up: `vp paper run --max-markets N` caps the snapshot, not the
  parsed markets, so a small N can yield nothing to forecast in EPL.
- `data/` is git-ignored; a session starts with no datasets. Rebuilding:
  `vp build-dataset --domain <d> --no-history` (20 s to 2 min), then
  histories for the markets to be backtested (about one per second).
- The SessionStart hook refreshes `uv` (the container's is too old for the
  pinned Python 3.14.7) and sets the git identity to the repository owner.
  Commits carry that identity and no assistant attribution.
- Running the whole platform: start `dockerd` as a background task, build
  with `docker build --network host --secret
  id=extra_ca,src=/root/.ccr/ca-bundle.crt --build-arg
  BASE=public.ecr.aws/docker/library/python:3.14-slim -t vibe-predict:dev .`
  (Docker Hub pulls are refused here), then `docker compose -f
  deploy/compose.yaml -f deploy/compose.proxy.yaml up -d` with
  `VP_DB_HOST=localhost VP_DB_PORT=5433 VP_S3_HOST=localhost
  VP_POSTGRES_IMAGE=public.ecr.aws/docker/library/postgres:16
  VP_PUBLIC_URL=http://127.0.0.1:8000` and a generated `VP_MASTER_KEY`
  exported. Sign-in links are in the web container's `/data/outbox`; the
  owner's database is `psql -h 127.0.0.1 -p 5433 -U postgres -d vp` inside
  the Postgres container. Restart only the services a change touches
  (`up -d --no-deps web`): recreating the data worker cuts a dataset build
  short (it resumes, but a job dies after three attempts). Sign-in allows
  twenty requests an hour per address; reuse session cookies in scripts.
- Checking the platform visually: start `vp serve` from a script file,
  then drive Chromium as below through sign-in (read the link from
  `<data root>/outbox/`). Real-browser runs have found faults request tests
  cannot, such as `Origin: null` under a strict referrer policy.
- The interface's words are all in `vp/ui/static/app/locales/en.json`;
  `tests/test_ui_catalogue.py` fails if the code uses a key the catalogue
  lacks. Messages are trusted text; values are escaped by `t()` unless
  wrapped in `raw()`, and `tp()` gives plain text for attributes.
- Checking the interface visually: run `vp ui` on a data root, then
  Playwright with the preinstalled Chromium
  (`executable_path="/opt/pw-browsers/chromium"`, `args=["--no-proxy-server"]`,
  because the container's proxy otherwise breaks localhost subresources),
  via `uv run --with playwright`. Put server start and stop in a script
  file: a `pkill -f "vp ui"` typed inline matches the shell running it.
- `master` is kept fast-forwarded to the session branch at the user's
  request; work on `master` directly when the session allows it.

## Invariants to preserve

- A market's label `resolved_outcome` is set only from settlement evidence
  (CLOB `winner` flag or a final oracle status), never from a price. Closed
  is not resolved.
- The first outcome of every record is the event being forecast; forecast,
  market price and label all refer to it.
- Every forecaster will take an explicit information cutoff and must not
  read anything after it.
- Live execution is hosted only and built last (Phase 22). No
  order-signing code is written until the security design's version 2
  (Phase 22, task 112, revising `docs/security.md`) is agreed with the
  user.

## Commands

```bash
uv sync                          # environment (the SessionStart hook does this on the web)
uv run pytest -q                 # tests
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pre-commit run --all-files
```

`pre-commit run --all-files` checks only files git already tracks, so a
new file is skipped until it is staged: run `git add -A` first, or run the
three CI commands above, before committing. Twice on 2026-09-23 a new
file with a lint error passed pre-commit locally and failed CI.
