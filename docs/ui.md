# Browser Dashboard

`vp ui` serves a local, read-only dashboard over the data root: what is on
disk, every backtest run with its tables and figures, the paper ledger with
accounts, positions and settlements, and the latest market snapshot per
domain. It is the view; the commands remain the way things happen.

```bash
uv run vp ui --root data          # http://127.0.0.1:8765/
```

## Design

- **Standard library only.** The server is `http.server` with a handful of
  JSON endpoints and one static page; no framework, no build step, no new
  dependency. It binds to localhost, reads the same files the commands
  write, holds no state, and cannot write anything, so it can be started
  and stopped at any time and exposes no surface an execution adapter
  could be reached through.
- **One page, no framework.** `vp/ui/static/index.html` is hand-written
  HTML, CSS and vanilla JavaScript: a header with four views, cards for
  counts, plain tables, the backtest figures inline. It uses the system
  font, a neutral palette, tabular numerals, and follows the system light
  or dark theme. Positive and negative returns and skill are coloured;
  nothing else is.
- **Cached reads.** Parquet reads are keyed by file modification time, so
  the 134k-row weather set is read once per change; the overview reads
  only the two columns it needs.

## Endpoints

| Path | Returns |
| :--- | :--- |
| `/` | the page |
| `/api/overview` | per-domain counts (resolved markets by kind, histories, snapshots, backtests) and paper accounts |
| `/api/backtests` | every run under `data/backtests/`, with its summary tables parsed and figure names |
| `/api/backtests/<domain>/<stamp>/<figure>.png` | a figure |
| `/api/paper?limit=N` | ledger integrity, accounts, open positions, settlements, recent entries |
| `/api/snapshots/<domain>` | the latest snapshot's markets with quotes and parsed fields |
| `/api/forecasts?limit=N` | the most recent paper forecasts |

Unknown paths and path traversal return 404. Tests start the server on a
free port against the fixtures of the other test files and check each
endpoint's content.

## What It Is Not

It is not a control panel: there are no buttons that run a cycle, place
an order or edit a mandate, and there will not be until the live security
design is agreed, because a browser page that can act is an attack
surface the design has to cover. The dashboard shows; the operator acts
from the shell, where every action is a ledger entry.
