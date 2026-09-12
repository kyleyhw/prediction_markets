# Phase 6 Test Report: Restructure and Archive

Date: 2026-09-12. Environment: Python 3.14.0rc2 via `uv 0.8.17`, Linux
container. Total runtime of all checks below: about 13 s wall.

## Purpose

Phase 6 archived the original project, renamed the package to `vp`, and ported
three modules from Vibe-Trading. The checks verify that the ported code is
correct where it matters for later phases, namely the settlement logic that
scoring depends on and the bankroll arithmetic, and that the tooling gates
work.

## Static Checks

| Check | Command | Result | Runtime |
| :--- | :--- | :--- | ---: |
| Lint | `uv run ruff check .` | passed, 0 findings | < 1 s |
| Format | `uv run ruff format --check .` | passed, 12 files | < 1 s |
| Types | `uv run ty check` (`error-on-warning`) | passed, 0 diagnostics | < 1 s |
| Secrets | `detect-secrets scan --baseline .secrets.baseline` | passed, no findings | < 1 s |
| Hooks | `uv run pre-commit run --all-files` | all four hooks passed | 12.0 s (includes first-time hook environment install) |
| Entry point | `uv run vp --version` | prints `vp 0.1.0` | < 1 s |

The archive is excluded from ruff and ty, and pytest is scoped to `tests/`, so
the archived project's own tests, which import the old `src` package, are not
collected.

## Unit Tests

`uv run pytest -q -s`: 20 passed in 0.14 s (0.47 s wall including startup).

### `tests/test_bankroll.py`

**What.** Ten tests of `vp.backtest.bankroll`: equity curve, maximum drawdown,
per-bet returns, descriptive statistics, the permutation test, the bootstrap
interval and walk-forward consistency.

**Why.** The module was rewritten from bar-based upstream code onto per-bet
P&L arrays, so its arithmetic had to be re-verified from scratch rather than
trusted from the source.

**Test data.** One sequence of five bets with P&L `[10, -5, 20, -30, 15]` on a
bankroll of 100. It was chosen because it is short enough to check by hand and
still exercises a win, a loss, a new high, a drawdown from that high and a
partial recovery, giving equity 110, 105, 125, 95, 110. Expected values are
derived analytically: drawdown $(95 - 125)/125 = -0.24$; profit factor
$45/35$; the second walk-forward window's return $110/105 - 1$. Two extra
sequences target edge cases: `[-10, 5]` checks that a first-bet loss registers
against the initial-cash high-water mark, and `[-100, 10]` checks that a return
after ruin is reported as 0 rather than infinity. Randomised tests draw their
seed with NumPy in a session fixture and print it, so a failure is
reproducible; they check p-values lie in $[0, 1]$, interval bounds are
ordered, and the same seed reproduces the same result.

### `tests/test_polymarket.py`

**What.** Ten offline tests of `vp.venues.polymarket`: market and event
normalisation, the resolution-evidence ladder, lifecycle status, and the CLOB
token-id domain check.

**Why.** Scoring a forecast against a wrongly inferred outcome corrupts every
downstream statistic. The ladder distinguishing *closed* from *resolved* is
therefore the part of the client that must be pinned by tests, and it is pure
logic over payload fields, so it can be tested without the network.

**Test data.** Fixture payloads built from the field names the module
documents (Gamma list fields JSON-encoded as strings, as upstream observed).
Cases: an open market; a closed market with no oracle record and a pinned
price, which must be `pending` with an inference only; a final oracle status
with one pinned price, which names the winner; a final status with prices
0.5/0.5, which is `resolved` with no winner; `proposed`, which is `pending`; a
pinned price on an open market, which is not settlement; the CLOB `winner`
flag, which names the winner directly; an archived market, whose status is
`archived` while its resolution is still reported; an event with one resolved
and one pending market, which must be `pending`; and the token-id boundaries
$2^{63}$ and $2^{256}$.

## Live Smoke Test

**What.** A script exercising `search_events`, `fetch_event`, `fetch_market`
with book depth, `fetch_history`, and a resolved market via its condition id.

**Result: failed to run.** Every request was refused before reaching
Polymarket:

```
requests.exceptions.ProxyError: HTTPSConnectionPool(host='gamma-api.polymarket.com', port=443):
Max retries exceeded ... (Caused by ProxyError('Unable to connect to proxy',
OSError('Tunnel connection failed: 403 Forbidden')))
```

The container's egress proxy status endpoint records the cause as
`connect_rejected: gateway answered 403 to CONNECT (policy denial)` for
`gamma-api.polymarket.com:443`. This is the development container's network
policy, not a defect in the client, and routing around it is not permitted.

**Fix.** None possible in this environment. The live test is carried into
Phase 7 task 8 (dataset verification), to be run from a machine with access to
`gamma-api.polymarket.com` and `clob.polymarket.com`. The bankroll half of the
same script passed and is superseded by `tests/test_bankroll.py`.
