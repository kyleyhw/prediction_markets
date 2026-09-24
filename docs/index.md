# Documentation Index

`vibe-predict` is an LLM forecaster for binary prediction-market contracts on
Polymarket, scored by backtest and paper trading before any live execution. The
[README](../README.md) gives the overview and quick start; the
[project plan](../PROJECT_PLAN.md) gives the phased roadmap and its status.

- [Architecture](architecture.md): package layout, data flow, and the design
  decisions behind them.
- [Data layer](data_layer.md): the market record, domain adapters, discovery,
  the resolved dataset and snapshots.
- [Forecasters](forecasters.md): the contract, the cutoff-bounded evidence
  object, the baselines, Elo, and the LLM forecaster's prompt design and
  failure modes.
- [Scoring](scoring.md): proper scores, skill against the market, the
  reliability diagram and Murphy decomposition, bankroll statistics.
- [Sizing](sizing.md): edge, Polymarket's fee formula, Kelly and fractional
  Kelly.
- [Paper trading](paper_trading.md): the hash-chained ledger, the forward
  cycle, settlement and the leakage check.
- [Product design](product.md): the hosted app for everyone, Phases 13
  to 23: architecture, accounts and money, the experience, sequencing.
- [Platform](platform.md): Phase 13 as built: configuration, the
  principal and tenancy, storage, jobs and worker pools, the market-data
  service, evidence, budgets and keys, observability and the local
  stand-in.
- [Evidence sources](evidence.md): what the collectors capture, from
  where, and on what terms; how the archive is read without seeing past a
  cutoff, and the point-in-time sources (Phase 17).
- [Opening a new domain](domains.md): the onboarding kit and the
  candidate domains ranked by what the venue lists (Phase 17).
- [Collaboration and delivery](collaboration.md): teams and roles,
  public shares and forks, comments, leaderboards, notifications, chat
  channels with pairing, scheduled briefs, webhooks and the read-only MCP
  server (Phase 18).
- [The shadow forecaster](shadow.md): a public address's record as a
  report card: diagnostics, the rule that describes it, the counterfactual
  (Phase 19).
- [Portfolio, risk and health](portfolio.md): open positions as one
  portfolio, simultaneous Kelly, strategy health and the promotion
  protocol (Phase 20).
- [Runbook](runbook.md): what each alert means and what to do.
- [Scaling](scaling.md): tenancy, storage, the job queue, the market-data
  service, LLM cost controls, the capacity model and the growth path for
  many users.
- [Vibe-Trading review](vibe_trading.md): what the reference implementation
  is and has, its collaborative tools, the capability mapping to this
  project's phases, and the non-infringement rules.
- [Documentation site](site.md): the public site's structure, build rules
  and the default "paper" visual style, with the alternatives to trial.
- [Interface](interface.md): the browser app for everyone: guided start,
  home, market cards, strategies, backtests, Learn and Settings in Simple
  and Detailed reading levels; words, formats and accessibility.
- [Usability sessions](usability.md): the protocol for watching people
  new to prediction markets use the app (Phase 14, task 49).
- [Strategies from conversation](strategies.md): the strategy spec
  (markets, belief, rule, sizing, schedule), what a prompt may override,
  props, model tiers, the compiler, preview, number gate and lifecycle
  (Phase 15).
- [Signals and the benchmark](signals.md): the signal contract and its
  gates, the library, the bench against the market, blends, committees,
  contamination and the weekly benchmark with sealed forecasts (Phase 16).
- [Browser dashboard](ui.md): the Phase 12 page the interface grew from,
  and `vp ui`, the developer's local view over a data root.
- [Security design](security.md): version 2, proposed for hosted live
  execution (session keys, the execution service, the mandate a person
  signs, the order gate, jurisdiction), on the safety layer built in
  Phase 11; agreement is required before any order-signing code.
- [Venues](venues.md): the Polymarket US assessment, a proposed decision.
- [Provenance](provenance.md): what was adapted from Vibe-Trading, how it was
  changed, and why.

Test reports live in [tests/reports/](../tests/reports/), one per phase:
[Phase 6](../tests/reports/phase6_restructure.md),
[Phase 7](../tests/reports/phase7_data_layer.md),
[Phase 8](../tests/reports/phase8_forecasters.md),
[Phase 9](../tests/reports/phase9_backtest.md),
[Phase 10](../tests/reports/phase10_paper_trading.md),
[Phase 11 safety layer](../tests/reports/phase11_safety_layer.md),
[Phase 13 platform](../tests/reports/phase13_platform.md),
[Phase 14 interface](../tests/reports/phase14_friendly.md),
[Phase 15 strategies](../tests/reports/phase15_strategies.md),
[Phase 16 signals](../tests/reports/phase16_signals.md),
[Phase 17 evidence](../tests/reports/phase17_evidence.md),
[Phase 18 collaboration](../tests/reports/phase18_collaboration.md),
[Phase 19 shadow forecaster](../tests/reports/phase19_shadow.md),
[Phase 20 portfolio](../tests/reports/phase20_portfolio.md),
[Phase 21 scale](../tests/reports/phase21_scale.md) and
[Phase 23 site](../tests/reports/phase23_site.md). Phase 12 is
continuous (documentation, hooks and the `vp ui` page in [ui.md](ui.md))
and has no report of its own.
The original project's documentation is preserved under
[archive/prediction_markets/docs/](../archive/prediction_markets/docs/).
