# The Interface

The browser app a person uses: a guided start, a home screen, markets,
strategies, backtests, Learn and Settings, each in two reading levels. It
is plan tasks 39 to 47 (Phase 14, pulled forward by the build order of
2026-09-23) built on what the engine already writes, and it replaces the
single-page dashboard of Phase 12 (`ui.md`), whose charts, glossary and
fonts it keeps. The design it follows is `product.md`, "The Experience".

```bash
uv run vp serve                    # hosted: sign in, http://127.0.0.1:8000/
uv run vp ui --root data           # a developer's local view, no accounts
```

## One Page, Two Servers

The same files serve both. `vp serve` puts them behind sign-in, keeps each
person's settings in Postgres and never shows the server's paths; `vp ui`
is the developer's read-only view of a data root, with no accounts, where
settings stay in the browser and an empty state also names the command
that would fill it. The page tells the two apart by asking `/auth/me`:
only `vp serve` answers with JSON.

The frontend is build-free, as `product.md` decided: ES modules served as
static files, no bundler, no framework, nothing to install to work on it.

| File | What it holds |
| :--- | :--- |
| `static/index.html` | the shell: skip link, side bar, `<main>`, the popover |
| `app/app.css` | the "paper" tokens (`site.md`, section 4) and every style |
| `app/main.js` | settings at start-up, the side bar, the reading-level switch, the hash router |
| `app/i18n.js` | message lookup, plurals and number, money and date formatting |
| `app/locales/en.json` | every word the app shows, glossary included |
| `app/api.js`, `app/prefs.js` | the server, and the person's settings |
| `app/ui.js`, `app/charts.js` | shared pieces: terms, tables, empty states, fee and chance sentences; the SVG charts |
| `app/views/*.js` | one module per screen: `home`, `markets`, `market`, `strategies`, `backtests`, `learn`, `settings`, `start` |

A view is an async function that returns HTML and registers, with
`after()`, the code that wires its controls once the HTML is in the page.

## Reading Levels (task 39)

One switch in the side bar, saved with the person's settings, and every
screen written both ways. The rule from `product.md` is the test each
screen was held to: **Simple never omits a fact that would change a
decision; it changes the words and the density.** In practice that means
some facts appear in both levels however plain the page:

- the fee a buyer pays, in cents a share;
- that a record of trades failed its integrity check;
- that a backtest assumed no fees, or rests on too few markets to tell
  skill from luck (fewer than 350, the count the plan's power rule gives
  for a two-point Brier edge);
- that a sample strategy's forecasts were less accurate than the market's
  own prices.

Simple mode names the sample strategies in words ("Team ratings" for
`elo`) with a sentence each, shows prices as chances ("62% chance"), and
says every number in a sentence. Detailed mode shows the internal names,
every score and interval, and renders each technical term as a dotted
button whose definition, with the documentation page that carries its
derivation, opens on click or Enter and closes with Escape.

## The Screens

**Guided start (task 40).** Five screens, one button each: what this is
(with the statement that it is a tool, not advice, and uses no real
money), pick interests, a few of your markets, choose the sample strategy
Home follows, choose a reading level. Every screen can be skipped; the
step reached is saved, so a person who leaves half-way is offered to pick
up where they left off. A brand-new person is taken there on their first
visit; nobody is sent there twice.

**Home (task 41).** The followed sample strategy's play-money balance,
its change since it started, how it compares with doing nothing, its open
positions and fees paid, and its balance chart; what changed in the last
24 hours, counted from the ledger; and one next step, chosen from the
person's state (no interests yet, nothing running, positions waiting,
otherwise the markets). Detailed adds every strategy's balance, realised
profit, open stake, fees, settled count and skill so far, their curves
together, and the ledger's integrity.

**Markets (task 42).** Cards for the open markets of one interest, from
the latest snapshot, interests first: the question, the chance with a
bar, when it closes in relative words, the fee to buy, and a note when no
one is offering to trade. Search filters in place; markets without a book
are hidden unless asked for. A market's page adds the chance over time,
drawn from the market's price in each recent snapshot (the only history
an open market has until the market-data service lands, build order step
3), and what the sample strategies forecast for it; Detailed adds the
order book, the fee formula with the market's own rate, the parsed fields
and the identifiers.

**P&L with a baseline (task 43).** Wherever money is shown there is a
chart with **doing nothing** drawn dashed alongside: the starting amount,
unchanged. Doing nothing is the same as following the market, because a
strategy whose forecast is the market price never finds an edge and never
bets; so "better than doing nothing" is visible without reading a number.
Each chart has a one-sentence description for screen readers and a "show
the numbers" table beneath it.

**Fees (task 44).** Every market card says what buying costs, from the
market's own rate (the client reads `feeSchedule` since 2026-09-23;
`sizing.md`): "Fee to buy: about 1.2¢ a share", or that the venue states
none. Paper positions say how much of the stake was fees, Home says what a
strategy has paid in total, and a backtest that assumed no fees says so in
both levels. Learn has a page on fees with the fee curve.

**Learn (task 45).** Six short pages: what a prediction market is, why
the price is a forecast, what a backtest is and is not, paper trading,
what trading costs, and why beating the market is hard. Each is plain
language with a picture drawn in the page; Detailed adds the formulas,
the `docs/` page with the derivation, and references, including the
platform's own Phase 9 result that no baseline beats the market and the
Forecasting Research Institute's ForecastBench update of October 2025, in
which a leading language model trailed superforecasters by about 0.02
Brier.

**Settings (task 46).** Reading level, theme, language and formats,
interests, the sample strategy Home follows, and the guided start again.
Each control saves as it changes and says so in a status line that a
screen reader announces. Detailed adds API tokens (create, shown once;
revoke), a download of every record the app holds for the person, and a
list of what is not here yet and when it arrives: the play-money amount
(with the person's own paper account), notifications (Phase 18), the
model tier (Phase 15), the budget and one's own key (task 35), data
refresh on demand (task 31). They are listed rather than shown as dead
controls, because a switch that does nothing misleads.

Settings are the person's, not the workspace's: one JSON document per
user in `user_settings` (migration 0003), readable only by its owner under
row-level security, validated by `SettingsBody` in `vp/platform/web.py`,
which refuses unknown keys, unknown interests and out-of-range steps. A
browser session may change them; an API token may only read them. The
browser keeps a copy so the first paint has the right theme and level.

**Strategies and Backtests.** The Phase 12 paper and backtest views,
rewritten for both levels. Simple says a backtest in sentences ("would
have turned $1,000 into $427 over 167 bets; worse than doing nothing; its
forecasts were less accurate than the market's own prices on these 60
markets"); Detailed keeps the score and bet tables, the reliability
diagram, the cumulative advantage and the comparison of two runs.

**Nothing dead-ends.** Every empty state says what fills it and offers a
way on. Where filling it needs work that has no button yet (a snapshot, a
paper cycle, a backtest), the hosted page says the platform does it and
points to Learn; the local page also shows the command.

## Words and Formats (task 47)

Every word comes from `locales/en.json`, looked up by key; plurals use the
locale's plural rules; numbers, money, percentages and dates are formatted
by `Intl` for the chosen locale, and "closes in 2 days" by
`Intl.RelativeTimeFormat`. A locale names a catalogue and a formatting
region: English ships, as `en-GB` and `en-US`, which share the words and
differ in dates and separators. Adding a language is a new catalogue file
and a line in `LOCALES`.

Messages are trusted text; values inserted into them are escaped unless
explicitly marked as HTML. `tests/test_ui_catalogue.py` checks that every
key the code uses exists, that the keys built from fixed lists (Learn's
topics, the guided start's steps, the navigation) exist, that every
glossary entry is complete, and that no message carries a character that
would break out of an attribute.

## Accessibility (task 47)

The target is WCAG 2.2 AA in both themes and both levels.

- **Keyboard.** A skip link is the first stop; every control is a real
  link, button or form field; the reading-level switch is a pair of
  buttons with `aria-pressed`; glossary terms are buttons that open and
  close with Enter and Escape and return focus; after a navigation focus
  moves to the page heading, and the title names the page.
- **Screen readers.** Landmarks (`nav`, `main`), `aria-current` on the
  current section, form groups with legends, table captions and column
  headers, `role="status"` for saved settings and search counts, and on
  every chart an `aria-label` sentence plus the table of its numbers.
- **Contrast.** The "paper" palette was measured before use: text at least
  4.5:1 against every surface (ink 14.9 and 13.8, muted 5.9 and 6.6,
  accent 5.3 and 6.8, positive 4.7 and 8.1, negative 5.7 and 6.3, light
  and dark) and chart series at least 3:1 (3.8 to 7.5).
- **Targets and reflow.** Buttons and fields are at least 40 px tall, the
  level switch 30 px; at 390 px wide the side bar becomes a top bar and
  nothing scrolls sideways.
- **Audit.** A Chromium run with axe-core's WCAG 2.0, 2.1 and 2.2 A and AA
  rules over every screen in both levels, both themes and both servers;
  the result is in the Phase 14 report and below.

## Security

Scripts come only from this origin: `vp serve` sends a
Content-Security-Policy with `script-src 'self'` and no inline script on
every page except FastAPI's API reference, so text from a market question
or a ledger entry that slipped past escaping still could not run.
Everything from the server is escaped where it is inserted. The page still
cannot act: it reads, and it changes only the person's own settings and
API tokens. The engine-facing commands stay on the command line until
jobs exist (task 31).

## Endpoints Added

| Path | Returns |
| :--- | :--- |
| `GET /api/settings` | the person's settings, defaults until saved (`vp serve`) |
| `PUT /api/settings` | replaces them; browser session only |
| `GET /api/markets/<domain>/<id>` | one market: book depth, fee terms, forecasts, its price across recent snapshots |

`/api/overview` now carries each domain's title and summary (from the
engine's `Domain`, so a new domain brings its own words) and, under `vp
serve`, no server path; `/api/paper` adds per-account fees paid, the time
of each point on the balance curve, skill so far against the market, and
the counts of the last 24 hours; snapshot rows add the outcome names and
fee terms.

## Verified

Recorded in the Phase 14 report when it is written (task 49); the browser
run of 2026-09-23 is summarised in the plan under task 47.

## Known Gaps

- Everyone on one `vp serve` sees the same sample strategies, because the
  data root is still shared (task 30). The settings are per person.
- The chance-over-time chart reads the last 30 snapshots; the snapshot
  reader's cache grows with the snapshots read and is not bounded.
- Usability sessions with people who have never used a prediction market
  (task 49) are what will show whether the words work; they need a public
  host and come at the end of the build.
