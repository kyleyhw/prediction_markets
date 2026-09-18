# Product Design: the Hosted App

vibe-predict becomes a web app people open in a browser, with no
terminal, no repository and no installation anywhere in the user's story.
Developers and the operator keep the command line: the `vp` commands, the
tests, and deploys from CI stay as they are. This page is the design
behind Phases 13 to 16 of the plan. The engine (`vp/`) stays as it is;
what changes is who can reach it and how.

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
browser  ──HTTPS──▶  web service (FastAPI)  ──▶  Postgres (users, strategies,
   │                     │                            ledgers, forecasts, jobs)
   │                     ├──▶ vp/ engine (unchanged)
   │                     └──▶ shared data volume (Parquet datasets, histories,
   │                                                snapshots)
   └── wallet extension   worker (same image): job queue + schedules
       (Phase 16 only:    ├── hourly: snapshot open markets, paper cycles, settle
        signs orders       ├── daily: refresh resolved datasets and histories
        client-side)       └── on demand: backtests, strategy previews, LLM calls
```

- **Engine.** `vp/` as today. The service imports it; nothing in the engine
  knows about users or HTTP. Per-user work (a backtest, a paper account)
  runs the same functions with a per-user data root and ledger.
- **Service.** FastAPI, chosen because it is the standard for a typed Python
  API with sessions and background work and because its OpenAPI page is
  the API documentation for the technical user. Endpoints mirror the CLI:
  build, snapshot, backtest, paper run, settle, leakage, plus auth,
  strategies and settings.
- **Storage.** Postgres for everything per user and for the job queue;
  Parquet on a shared volume for market data, exactly the files `vp`
  already writes. Per-user ledgers keep the hash chain, one chain per user.
- **Jobs.** A worker process runs a queue table in Postgres (no extra
  broker) with scheduled entries for snapshots, cycles, settlements and
  dataset refreshes, and on-demand entries for backtests and LLM runs.
  Every job reports progress the page can show.
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
  lose real money in the product as shipped in Phases 13 to 15.
- **LLM calls are paid by the product**, with a monthly budget per user
  shown in the app, because asking a non-technical person to obtain an API
  key defeats the purpose. Technical users may add their own key, stored
  encrypted server-side, to lift the budget. The default model for user
  strategies is Sonnet 5 with a per-user monthly cap in dollars (proposed
  default $5, adjustable by the operator); backtests show their cost before
  they run.
- **Live execution** (Phase 16) is non-custodial: the server prepares an
  order, the user's wallet extension signs it in the browser, and the
  signed order is submitted. The server never holds a key. The mandate,
  kill switch, approvals and audit ledger from `docs/security.md` apply
  unchanged; the keyring section is replaced by client-side signing.
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

Phase 13 makes the browser the whole product for one person: service,
accounts, per-user state, jobs, deploy, and the existing views on top.
Phase 14 makes it friendly: the guided start, Simple mode, plain language,
Learn, Settings, P&L charts. Phase 15 is the vibe-to-strategy pipeline,
designed first and separately, which lands as the "New strategy" button in
a product that already has users who understand what it will do. Phase 16
is hosted live execution behind the revised security design. Phase 12's
rule holds throughout: each phase lands with its page and its report.

## Open Questions, to Settle Before Each Phase

- Hosting provider and region (Phase 13).
- Who the operator is for budgets and abuse (Phase 13).
- Whether Simple mode shows fees at all before Phase 16 (Phase 14: proposed
  no, since paper trading has none).
- The strategy spec, sizing defaults and how a prompt overrides them
  (Phase 15, its own design page).
- Which wallet flow Polymarket's CLOB supports for browser signing at the
  time (Phase 16).
