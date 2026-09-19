# Product Design: the Hosted App

vibe-predict becomes a web app people open in a browser, with no
terminal, no repository and no installation anywhere in the user's story.
Developers and the operator keep the command line: the `vp` commands, the
tests, and deploys from CI stay as they are. This page is the design
behind Phases 13 to 23 of the plan. The engine (`vp/`) stays as it is;
what changes is who can reach it and how. The platform is designed for
many users from its first release; the tenancy, storage, queue and
capacity design is in [scaling.md](scaling.md), and the reference
implementation's collaborative tools, rebuilt here for many workspaces,
are mapped in [vibe_trading.md](vibe_trading.md).

## Who It Is For

Two people have to be equally at home, and the same product serves both:

- **Someone new to all of it.** Has talked to a chatbot, uses a browser,
  has never seen a prediction market, has no technical or mathematical
  background. Must be able to understand what a price of 0.62 means, watch a
  paper strategy run, and eventually describe a strategy in a sentence and
  see how it would have done, without ever meeting the words "Brier",
  "Kelly" or "git".
- **An experienced trader or a hard-STEM graduate.** Wants the reliability
  diagram, the bootstrap interval, the fee model, the cutoff semantics and
  the raw records, and wants nothing hidden or rounded away.

The rule that reconciles them: **one backend, two reading levels.** Every
number is computed once, by the same code, and rendered either in plain
language or in full. Nothing is made less rigorous for the first person;
it is only explained.

## Why Hosted

A hosted app is the only form with no terminal for the user: they open a
URL. The operator deploys by pushing to the repository, and keeps the
command line for everything else. It is also
the most portable (phone, tablet, any computer) and lets the shared data
(datasets, snapshots, histories) be fetched once for everyone rather than
once per machine. Its costs are real and are planned for below: accounts,
per-user state, background jobs, paying for LLM calls, and a different
security model for live execution, in which the server never holds a
wallet key.

## Architecture

```ascii
browser / chat channels / MCP clients / API tokens
        │ HTTPS, every request carries a principal (user, workspace, roles)
        ▼
web service (FastAPI, stateless replicas) ──▶ Postgres (workspaces, strategies,
        │                                      runs, forecasts, per-account
        ├──▶ vp/ engine (unchanged)            hash-chained ledgers, jobs,
        │                                      budgets; row-level security)
        └──▶ object storage (dataset versions, histories, snapshots,
                             evidence archive, artifacts, ledger archives)
                                                  ▲
workers (same image, pools per job kind)          │
   ├── forecast (LLM, statistical), backtest, paper cycle, settlement
   ├── evidence capture, dataset build, delivery (email, Telegram, ...)
   └── scheduler: cron with time zones, enqueues jobs
market-data service (same image): one WebSocket subscription to the venue
   for every tracked market, keyset discovery, resolutions, quotes coalesced
   per minute, the snapshot files vp already writes, fan-out to consumers
wallet / session key (Phase 22 only): the user's delegated signer, scoped
   and revocable, never the wallet key; mandate, gates and halts around it
```

- **Engine.** `vp/` as today. The service imports it; nothing in the engine
  knows about users or HTTP. Per-user work (a backtest, a paper account)
  runs the same functions with a per-user data root and ledger.
- **Service.** FastAPI, chosen because it is the standard for a typed Python
  API with sessions and background work and because its OpenAPI page is
  the API documentation for the technical user. Endpoints mirror the CLI:
  build, snapshot, backtest, paper run, settle, leakage, plus auth,
  strategies and settings.
- **Storage.** Postgres for everything per workspace and for the job
  queue, with row-level security keyed on the request's principal; Parquet
  in object storage for market data, exactly the files `vp` already writes,
  as immutable dataset versions. Per-account ledgers keep the hash chain,
  one chain per account, verifiable offline with the existing code.
- **Jobs.** Workers run a queue table in Postgres (no extra broker at
  first) with a pool per job kind, so a slow LLM queue never delays a
  settlement; scheduled entries for snapshots, cycles, settlements and
  refreshes, on-demand entries for backtests and LLM runs, idempotency
  keys, retries and progress the page can show. A single market-data
  service holds the venue subscription for everyone; users never poll the
  venue.
- **Deploy.** One container image holding web and worker, one Postgres, one
  volume, on a host with push-to-deploy (Fly.io or Render); GitHub Actions
  runs the tests and deploys `master`. Operator actions (refresh data,
  pause a user, set budgets, read costs) are `vp admin` commands first and
  an admin page only if they turn out to be needed often.
- **Frontend.** The existing hand-written page grows into a small
  build-free app: ES modules served statically, the same fonts and charts,
  a router, and forms. No bundler, no framework, so there is still no
  toolchain to install to work on it.

## Accounts and Money

- **Sign-in** by email magic link (no passwords to store) with OAuth later.
- **Paper first.** Every account starts with a paper bankroll and can never
  lose real money in the product as shipped in Phases 13 to 20.
- **LLM calls are paid by the product**, with a monthly budget per user
  shown in the app, because asking a non-technical person to obtain an API
  key defeats the purpose. Technical users may add their own key, stored
  encrypted server-side, to lift the budget. The default model for user
  strategies is Sonnet 5 with a per-user monthly cap in dollars (proposed
  default $5, adjustable by the operator); backtests show their cost before
  they run.
- **Live execution** (Phase 22) never holds the user's wallet key. The
  proposed model is the venue's session keys: a delegated signer the user
  authorises on the venue, scoped to trading, unable to withdraw, expiring
  in 180 days and revocable by the user at any time independently of us,
  held under envelope encryption; the user's wallet signs only the mandate
  commit and high-value approvals in the browser. The mandate, kill
  switches, approvals and audit ledger from `docs/security.md` apply; the
  keyring section is replaced by this model in the design's version 2. Live
  execution is offered only to strategies that passed the promotion
  protocol (Phase 20) and only where the venue serves the user.
- **Compliance.** Prediction markets are restricted in several
  jurisdictions and Polymarket itself geo-fences. Before public launch the
  app needs terms of use, an age gate, a jurisdiction notice, and the
  honest statement, on the first screen, that this is a tool for building
  and testing strategies and not advice. This is listed as a task, not
  resolved here.

## The Experience

Brokerage apps are the model: a home screen with your position, a way to
browse the market, a way to act, and a place to learn.

| Screen | Newcomer sees | Expert sees (Detailed) |
| :--- | :--- | :--- |
| **Home** | Your play-money balance, its chart, what changed today, one next step | Per-strategy P&L, exposure, skill, settled counts |
| **Markets** | Cards: the question in plain words, "62% chance", closes in 2 days | Quotes, book depth, parsed fields, forecasts, history chart |
| **Strategies** | Your strategies as cards with a sentence each and a P&L line | Spec, selector counts, sizing, cost, every run |
| **Backtests** | "Would have turned $1,000 into $427 over 167 bets; worse than following the market" | Scores, calibration, bootstrap, charts, config |
| **Learn** | Short pages with pictures, from "what is a prediction market" up | Links into `docs/` derivations |
| **Settings** | Interests, play-money amount, reading level, theme | Model, budget, own key, data refresh, export |

Design rules:

- **Simple and Detailed** is one switch, remembered, and every screen has
  both renderings. Simple never omits a fact that would change a decision;
  it changes the words and the density.
- **Every number has a sentence in Simple mode** and a dotted term with a
  definition in Detailed mode (the glossary already built).
- **Prices are chances** in Simple mode ("62% chance"), prices in Detailed.
- **A P&L chart wherever money is shown**: home, each strategy, each
  backtest, with the market-following baseline drawn alongside so "better
  than doing nothing" is visible without a number.
- **First run is a guided start**: what this is, pick interests, see your
  markets, watch a sample strategy, make your own (Phase 15). Three to five
  screens, a button each, skippable.
- **Nothing dead-ends.** Every empty state says what fills it and offers
  the button that does so.

## Sequencing

Phase 13 makes the browser the whole product, built for many users from
the start: service, identity and workspaces, storage, jobs, the
market-data service, deploy, budgets, observability, and the existing views
on top. Phase 14 makes it friendly: the guided start, Simple mode, plain
language, Learn, Settings, P&L charts, fees shown honestly. Phase 15 is the
research session and the strategy spec, designed first and separately,
which lands as the "New strategy" button in a product that already has
users who understand what it will do. Phase 16 adds the signal library,
forecast committees and the public benchmark; Phase 17 the evidence
archive and new domains; Phase 18 teams, sharing, comments, leaderboards,
chat channels, scheduled briefs and the MCP server; Phase 19 the shadow
forecaster over a user's own public record; Phase 20 portfolio risk,
strategy health and the promotion protocol; Phase 21 the scale proof;
Phase 22 hosted live execution behind the revised security design, built
last so that strategies trade while the user's computer is closed; Phase
23 the documentation site and research lab, continuous. Phase 12's rule holds
throughout: each phase lands with its page and its report.

## Open Questions, to Settle Before Each Phase

The full table, with a proposal for each, is at the end of the
[project plan](../PROJECT_PLAN.md). The ones that gate the next phase:

- Hosting provider and region, and the object-storage provider (Phase 13).
- Who the operator is for budgets and abuse (Phase 13).
- Fees in Simple mode: now proposed yes, in cents, because the venue's 2026
  schedule charges takers on sports and weather markets (Phase 14).
- The strategy spec, sizing defaults and the fields a prompt may override
  (Phase 15, its own design page).
- The live key model: session keys for execution, browser signing for
  consent (Phase 22).
