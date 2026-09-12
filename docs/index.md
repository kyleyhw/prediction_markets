# Documentation Index

`vibe-predict` is an LLM forecaster for binary prediction-market contracts on
Polymarket, scored by backtest and paper trading before any live execution. The
[README](../README.md) gives the overview and quick start; the
[project plan](../PROJECT_PLAN.md) gives the phased roadmap and its status.

- [Architecture](architecture.md): package layout, data flow, and the design
  decisions behind them.
- [Data layer](data_layer.md): the market record, domain adapters, discovery,
  the resolved dataset and snapshots.
- [Provenance](provenance.md): what was adapted from Vibe-Trading, how it was
  changed, and why.

Pages for scoring, sizing and forecasters are added by the phases that
implement them. Test reports live in [tests/reports/](../tests/reports/); the first is the
[Phase 6 restructure report](../tests/reports/phase6_restructure.md) and
the [Phase 7 data layer report](../tests/reports/phase7_data_layer.md).
The original project's documentation is preserved under
[archive/prediction_markets/docs/](../archive/prediction_markets/docs/).
