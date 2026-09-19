# Provenance of Ported Code

Three modules in `vp/` are adapted from [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)
[[1]](#ref-vibe-trading), an MIT-licensed research workspace whose agent writes
and backtests strategy code for equities, crypto and futures. Its licence text
is reproduced in the root `NOTICE` file. The snapshot read was version
0.1.15, commit `afe7d7df585b8e8478f00408c66f49f1f09ead0c`.

Vibe-Trading was reviewed in full at the directory level and the reused
modules were read line by line before porting. The rest of it is not reused:
its backtest engines assume bar-indexed prices with margin, leverage and lot
sizes; its agent loop is built for code-writing agents; its live-trading layer
targets fourteen equity and crypto brokers; and its system prompt forbids the
model from producing numbers, so it contains no forecaster. What remains
useful beyond the three files is a set of design patterns adopted later in the
plan: the run-directory artifact layout, the hypothesis registry as a template
for a forecast registry, the hash-chained audit ledger, the filesystem kill
switch, and the hard-cap mandate with a fail-closed order guard.

## Ported Modules

| Target | Source | Lines | Changes |
| :--- | :--- | ---: | :--- |
| `vp/venues/_http.py` | `agent/backtest/loaders/_http.py` | 200 | Environment helper inlined; User-Agent identifies this project instead of imitating a browser. |
| `vp/venues/polymarket.py` | `agent/src/tools/prediction_market_tool.py` | 1241 | LLM-tool class, JSON envelope, parameter coercion and payload caps removed; functions raise instead of returning error dicts; typed public functions `search_events`, `fetch_event`, `fetch_market`, `fetch_book`, `fetch_history`. Endpoint spec, normalisation and resolution ladder kept verbatim in substance. |
| `vp/backtest/bankroll.py` | `agent/backtest/metrics.py`, `agent/backtest/validation.py` | 678, 505 | Rewritten over per-bet PnL arrays. Dropped: annualisation tables, trade-record classes, turnover, benchmark comparison, run-directory CLI. Kept: drawdown high-water mark seeded at initial cash, `ddof=1` guard, permutation test, bootstrap interval, walk-forward. Sharpe is per bet and not annualised. Seeds are required arguments. |

## Rationale for the Rewrite of the Numeric Modules

The plan for Phase 6 named two files to port. On reading them, both proved
tightly bound to bar-based trading: Sharpe is annualised through a table of
trading days and bars per session keyed by data source, and every statistic
consumes a `TradeRecord` with entry and exit prices, holding bars and margin.
A binary contract has none of these; it settles once at 0 or 1. Porting the
files unchanged would have carried several hundred lines of dead code into the
package, against the project's minimalism rule. The arithmetic and the guards
were therefore re-expressed on the natural object for this project, a per-bet
profit-and-loss array, in one module.

## Payload Caps

The upstream tool capped events at 30 markets, markets at 20 outcomes, books at
4 tokens and history at 1,000 points so that a tool result could never overflow
an LLM context. Those caps are removed here because this client feeds a data
pipeline, not a prompt: an event such as "Premier League winner" carries more
than 30 markets, and truncating it would silently bias the dataset. The event
resolution logic, which upstream had to reason about uninspected markets, is
simplified accordingly.

## Second Review, 2026-09-18

Vibe-Trading was read again in full at commit `e5f7195` (version 0.1.15
plus nine days of unreleased changes) for its product, its collaborative
tools and its scaling posture, to plan Phases 13 to 23. Nothing further was
ported: the upstream `prediction_market_tool.py` is unchanged in size (1,241
lines) since the first review, and the rest of the project is bound to
continuous-price instruments or to a single-operator runtime. What the
second review yielded is design patterns, each re-derived for binary
contracts under an explicit cutoff and never copied; they are listed with
the phase that adopts each in [vibe_trading.md](vibe_trading.md) § 7, and
the rules that keep the analogue clear of the original's name, marks,
assets and text are in its § 9. Any future port is recorded in the table
above with the upstream commit hash.

## References

<span id="ref-vibe-trading">[1]</span> HKUDS (2026). *Vibe-Trading: Your Personal Trading Agent.* Version 0.1.15. [Link](https://github.com/HKUDS/Vibe-Trading)
