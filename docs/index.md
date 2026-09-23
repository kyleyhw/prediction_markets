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
  where, and on what terms.
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
- [Browser dashboard](ui.md): the Phase 12 page the interface grew from,
  and `vp ui`, the developer's local view over a data root.
- [Security design](security.md): the proposed design for live execution
  and its implemented safety layer; agreement is required before any
  order-signing code.
- [Provenance](provenance.md): what was adapted from Vibe-Trading, how it was
  changed, and why.

Test reports live in [tests/reports/](../tests/reports/), one per phase:
[Phase 6](../tests/reports/phase6_restructure.md),
[Phase 7](../tests/reports/phase7_data_layer.md),
[Phase 8](../tests/reports/phase8_forecasters.md),
[Phase 9](../tests/reports/phase9_backtest.md),
[Phase 10](../tests/reports/phase10_paper_trading.md) and
[Phase 11 safety layer](../tests/reports/phase11_safety_layer.md).
The original project's documentation is preserved under
[archive/prediction_markets/docs/](../archive/prediction_markets/docs/).
