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
- [Browser dashboard](ui.md): `vp ui`, a read-only local page over the
  data root: datasets, backtests with figures, the paper ledger, markets.
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
