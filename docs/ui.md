# Browser Dashboard

> **Superseded as a page on 2026-09-23 by [the interface](interface.md)**,
> which keeps this page's charts, glossary, fonts and server and replaces
> the single hand-written page with the app described there. The server
> design below still holds for `vp ui`; the views and the palette are now
> the interface's.

`vp ui` serves a local, read-only dashboard over the data root: what is on
disk, every backtest run with its tables and charts, the paper ledger with
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
- **One hand-written page.** `vp/ui/static/index.html` is HTML, CSS and
  vanilla JavaScript: a left sidebar with the four views and a theme
  control (system, light, dark; remembered per browser), a page header,
  cards on an 8px spacing scale, tables with sticky headers and hover
  rows, and empty states that show the command to run.
- **Type.** Instrument Sans for text and JetBrains Mono for numbers, identifiers and
  axis ticks, vendored as latin-subset variable woff2 files under
  `static/fonts` (about 70 KB together, SIL Open Font License, see `NOTICE`), so
  the page works offline and makes no third-party request. Columns of
  numbers use tabular figures; large standalone numbers do not.
- **Charts drawn in the page.** The backtest runner writes `results.json`
  next to `summary.md` with the calibration bins, the cumulative Brier
  advantage series and the bankroll curves, and the page draws them as
  inline SVG in the theme's own colours: a reliability diagram with the
  diagonal, the cumulative advantage with a zero line, and the equity
  curves, each with a hover crosshair and a tooltip listing every series.
  The PNGs the runner also writes remain for the reports and for runs
  made before `results.json` existed, which the page falls back to.
- **Colour.** Each forecaster has a fixed colour slot (market blue,
  constant orange, Elo aqua, climatology yellow, LLM magenta) so a
  forecaster keeps its colour across runs, views and filters. The
  palette passes the colour-vision and contrast checks in both themes;
  every chart has a legend and a table beside it, so no value is carried
  by colour alone. Positive and negative skill and returns use the status
  colours and nothing else does.
- **Every term explains itself.** Each metric, market type, forecaster
  name and status is rendered as a dotted term; clicking it opens a
  definition with the direction that is better and the `docs/` page that
  carries the derivation. The definitions live in one `GLOSSARY` map in
  the page. Each view opens with a sentence on what it shows, each table
  and chart carries a caption, and rows open on click (a run from the
  overview, an entry's full record in the ledger, a market's parsed fields
  and forecasts).
- **Cached reads.** Parquet reads are keyed by file modification time, so
  the 134k-row weather set is read once per change; the overview reads
  only the two columns it needs.

## Views

- **Overview.** Per-domain cards with resolved-market counts and a stacked
  bar of market kinds; the latest backtest per domain as skill against the
  market; paper accounts with bankroll, realised profit, exposure and a
  sparkline of the bankroll over settlements; ledger integrity.
- **Backtests.** A list of runs on the left, one run displayed at a time
  with its score and bet tables and the three charts, and a control to
  overlay a second run's curves at reduced opacity for comparison.
- **Paper.** Account cards, open positions with the market price and the
  forecast drawn on one bar, settlements, and the ledger as a timeline.
- **Markets.** The latest snapshot of a domain, sorted by end date, with
  a search box, markets without a book hidden by default, the price as a
  bar, and a click on a row to show the parsed fields and any forecasts
  made on that market.

## Endpoints

| Path | Returns |
| :--- | :--- |
| `/` | the page |
| `/api/overview` | per-domain counts (resolved markets by kind, histories, snapshots, backtests) and paper accounts |
| `/api/backtests` | every run under `data/backtests/`, with `results.json` when present, its summary tables parsed and figure names |
| `/api/backtests/<domain>/<stamp>/<figure>.png` | a figure |
| `/api/paper?limit=N` | ledger integrity, accounts with bankroll curves and exposure, open positions, settlements, recent entries |
| `/api/snapshots/<domain>` | the latest snapshot's markets with quotes, parsed fields, a book flag and forecasts made on them |
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
