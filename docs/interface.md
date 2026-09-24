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
one is offering to trade. Soonest to close comes first; a market past
its closing date that the venue still lists says it was due to close and
has not settled, and comes after the rest (the live capture had dozens).
Search filters in place; markets without a book are hidden unless asked
for. A market's page adds the chance over time,
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
(with the person's own paper account) and the model tier (Phase 15).
Under `vp serve` it links Team, Notifications and Delivery (Phase 18). They are listed rather than shown as dead
controls, because a switch that does nothing misleads. Under `vp serve`,
Settings also shows this month's model spending against the budget (a
sentence in both levels, the breakdown by strategy, domain and model in
Detailed), and in Detailed one's own Anthropic key (shown only as its last
four characters) and a data refresh per domain.

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
Everything from the server is escaped where it is inserted. Under `vp
ui` the page cannot act. Under `vp serve` it starts work only as jobs in
the person's own workspace (next section), and every such request passes
the cross-site checks of the web service.

## Work From the Page (Phase 13)

Under `vp serve` the page starts work and shows it progressing:

- **Paper trading.** Home and Strategies show the sample strategies'
  account, which the platform trades every hour for everyone and says so
  (flag F17); Detailed offers its ledger to download and verify. A
  workspace with an account of its own sees that instead, with "run a
  cycle now" and "settle now".
- **Backtests.** Backtests has a form: the markets, the strategies, and in
  Detailed the hours before close and a cap on markets. Before anything
  runs it says how many markets the run covers and, if a model strategy is
  chosen, what it would cost and how much of the month's budget is left;
  an answer to an earlier choice that arrives late is ignored. A finished
  run opens itself.
- **The jobs panel.** Home, Strategies and Backtests list the workspace's
  recent jobs with their state, a progress bar and its message, and a
  cancel button while they are queued or running, polling every two
  seconds only while something is active.
- **What it cost.** Settings shows the month's model spending (above).

## Strategies of One's Own (Phase 15)

Hosted only (`vp ui` explains that the assistant needs the service):

- **Strategies** lists the person's own strategies with their status and
  first rendered line, then the sample strategies; it offers "Describe a
  strategy" and "Ask the research assistant".
- **Describe** (`#describe/new` or `#describe/<strategy>` to change one) is
  a conversation with the compiler. A proposal is shown as the engine
  renders it, in the same words for everyone, with what changed when
  refining and, in Detailed, the spec itself; "Run this" freezes exactly
  that. A question offers its choices as buttons; a refusal says what
  cannot be expressed. A suggested memory note is offered, never saved
  without a click.
- **A strategy's page** (`#strategy/<id>`) shows what runs, the preview
  (markets open now, settled markets a month, cost, the bets an edge
  needs), the run cards of its backtests with their caveats, its paper
  record (the sample strategies' view, full in Detailed), and in Detailed
  its versions and fingerprints. Buttons start a backtest or paper, change
  it, or stop it.
- **Research** (`#research/<conversation>`) shows answers with how many
  figures were checked against the data, or how many were replaced; in
  Detailed, every tool call with its input and result.
- **Settings** gains "What the assistant remembers": the person's notes,
  added and deleted there.

## Signals (Phase 16)

**Signals** (`#signals`, in the menu under both servers) shows, per
domain, the latest bench: in Simple one sentence ("0 of 10 signals beat
the market, 10 cannot be told apart from it, ...") and in Detailed the
table (markets, Brier, the market's Brier, the advantage with its
interval, the verdict, the markets an edge that size needs). Below it the
benchmark weeks, each with its questions and its sealed commitments (the
forecasts and scores once revealed), and in Detailed the library with
each signal's references and fingerprint. Under `vp ui` the benches are
read from `<root>/signals/bench/` and there is no benchmark.

A table wider than the screen scrolls inside its frame; the page makes
any such frame focusable and names it after the table's caption, so the
keyboard can scroll it (axe's scrollable-region rule).


| Path | Returns |
| :--- | :--- |
| `GET /api/settings` | the person's settings, defaults until saved (`vp serve`) |
| `PUT /api/settings` | replaces them; browser session only |
| `GET /api/markets/<domain>/<id>` | one market: book depth, fee terms, forecasts, its price across recent snapshots |
| `POST /api/strategies/compile` | queues one message to the compiler; returns the job and conversation |
| `POST /api/research` | queues one message to the research assistant |
| `GET /api/conversations/<id>` | the person's conversation and its turns |
| `POST /api/strategies/confirm` | freezes the spec of a stored turn as a version |
| `GET /api/strategies`, `GET /api/strategies/<id>` | the workspace's strategies; one with versions, runs, accounts |
| `GET /api/strategies/<id>/preview` | the newest version's preview |
| `POST /api/strategies/<id>/backtest`, `/paper`, `/retire` | start a backtest, open paper, stop |
| `GET /api/strategies/<id>/paper` | the newest account's paper view |
| `GET`, `POST /api/memory`, `DELETE /api/memory/<id>` | the person's memory notes |
| `GET`, `PUT`, `DELETE /api/packs/<domain>` | the platform's pack and the workspace's copy |
| `GET /api/signals` | the latest bench per domain and the library's manifest |
| `GET /api/benchmark` | recent benchmark weeks; commitments only until revealed |

`/api/overview` now carries each domain's title and summary (from the
engine's `Domain`, so a new domain brings its own words) and, under `vp
serve`, no server path; `/api/paper` adds per-account fees paid, the time
of each point on the balance curve, skill so far against the market, and
the counts of the last 24 hours; snapshot rows add the outcome names and
fee terms.

## Working Together (Phase 18)

Under `vp serve` the menu adds **Leaderboards**, **Team** and
**Notifications** (with the unread count beside it); **Delivery** opens
from Settings. A strategy's page gains sharing, the leaderboard entry and
comments, and a market's page gains comments. The pages, and why each
switch says what a stranger would see, are in `docs/collaboration.md`;
the words are under `team`, `notifications`, `leaderboards`, `delivery`,
`share` and `comments` in the catalogue. Verified in Chromium with zero
axe-core violations on 18 page states (`tests/reports/phase18_collaboration.md`).

## Your Record (Phase 19)

**Your record** (`#shadow`, from Strategies, hosted only): paste an
address, agree to link it, and read the report card. Simple gives three
sentences (the return and the prices taken, whether the market later
agreed, the costliest habit), the rule found if one held on held-out data
with "Try it as a strategy", and the caveats. Detailed adds every measure,
calibration, habits, the groups, the rules tried with their held-out
numbers, the counterfactual's parts and the peer context. Words under
`shadow` in the catalogue; design in `docs/shadow.md`.

## Verified

On 2026-09-23, in Chromium, against a data root built that day from the
live venue (120 Premier League markets with histories, 400 each of
Counter-Strike and weather, a backtest scoring 64 markets, and a paper
cycle of 360 captured markets and 36 orders, each paying its market's own
fee at rate 0.05), under both `vp ui` and `vp serve` (signed in through the
mail outbox):

- the guided start end to end, every screen in both reading levels, a
  third of them again in the dark theme, and three at phone width;
- axe-core's WCAG 2.0, 2.1 and 2.2 A and AA rules on 78 page renders: no
  violations (the one it found on the way, a link below the 24 px target
  size, was fixed);
- no console errors and no failed requests; no horizontal scroll at
  390 px; the skip link reaches `<main>`; a glossary term opens with
  Enter and Escape returns focus to it.

Balance charts were checked on a scratch copy of that root in which half
the open positions were settled with outcomes drawn at the market's own
price, since no real position had settled yet. The script lives outside
the repository, as the earlier browser checks did; `CLAUDE.md` says how
to repeat it. The words themselves wait for the usability sessions of
task 49.

## Known Gaps

- The chance-over-time chart reads the last 30 snapshots, one every
  fifteen minutes, so it spans about seven hours. The quotes table of the
  market-data service holds the longer series; the page does not read it
  yet.
- Usability sessions with people who have never used a prediction market
  (task 49) are what will show whether the words work; they need a public
  host and come at the end of the build.
