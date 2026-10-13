# The Demo on GitHub Pages

Decided 2026-10-13 by the owner: until the platform has a host and
sign-in, the public face of the project is a static demo on GitHub Pages,
free to run, and the full tool is each person's own copy (a fork). The
hosted platform with accounts (`docs/platform.md`) follows later and
reuses everything below.

## What a visitor can do

- **Describe a strategy to an AI**, in plain words, with their own model
  and key: Google's Gemini (a free key from AI Studio), Anthropic, OpenAI,
  OpenRouter, Groq and the other providers in `docs/models.md`, or a model
  on their own computer. The page asks the model exactly what the platform's
  compiler asks (`vp/strategy/compiler.py`: the same instructions, context
  and answer schema), checks the answer as the engine does, and shows the
  strategy in the engine's own words (`render`).
- **Or build one from a form**, with no key: always back the favourite or
  the underdog, or bet when a statistical forecaster (Elo, climatology, a
  signal) beats the price by a margin.
- **Run it on past markets**: every resolved market of the chosen domains
  that has a price history, at the time before settlement the strategy
  asks for. The page shows bets, profit, drawdown, fees and the forecast's
  skill against the market.
- **Download** the strategy (JSON, the spec) and the conversation with the
  results (Markdown). Nothing else is kept: there is no server to keep it.

## Why it can be static

Three things make a server unnecessary:

1. **Forecasts are computed ahead of time.** `vp demo` (`vp/demo.py`)
   exports, for each resolved market, its price and every statistical
   forecaster's probability at fixed cutoffs (1, 6, 24, 72 and 168 hours
   before settlement), through the same cutoff-bounded `Evidence` the
   backtest uses. A spec's own cutoff runs at the nearest of these, and
   the page says so.
2. **The rest of the backtest is arithmetic.** Selecting markets, sizing
   by fractional Kelly with each market's fee, settling and the statistics
   are ported to `pages/engine.js` line by line. `tests/test_demo.py` runs
   the Python engine and the page's engine on the same markets and fails
   on any difference in a bet, a stake or a score; the spec's checks and
   words are compared on sixty random specs across every domain.
3. **The visitor's browser calls the model.** Google's, Anthropic's and
   OpenAI-compatible APIs accept calls from a web page (Anthropic's with
   its `anthropic-dangerous-direct-browser-access` header). The key goes
   from the page to the provider only, is held in memory, and is gone when
   the tab closes.

A GitHub Action (`.github/workflows/pages.yml`) rebuilds the datasets every
day (their histories are cached between runs), exports them, builds the
documentation site into `docs/`, and publishes both. It needs Pages
enabled once: the repository's *Settings*, *Pages*, *Source: GitHub
Actions*.

## What it does not do, and why

- **No free model of the owner's.** A key in a static page is a public key.
  The owner pays nothing and lends nothing; visitors bring a key. The
  country rule of Google's free tier (`docs/models.md`) is then a matter
  between the visitor and Google, and the page says what Google's terms say.
- **No AI forecaster in the backtest.** Forecasting hundreds of markets
  with a model is hundreds of calls on the visitor's key; it runs on their
  own copy (`strategies/example_ai/`), where they choose how many.
- **No paper trading.** Paper trading needs something running between
  visits; on a copy, the platform does it (`docs/tutorials/run_your_own.md`).
- **No accounts, sharing or saved history.** Those are the hosted
  platform's.

## The fork path

A fork gets the same demo (its own Pages) and the harness: a strategy is a
spec plus, optionally, a Python script whose `forecast(market, evidence)`
is the belief (`vp/strategy/script.py`, `strategies/README.md`, which is
written for the AI that writes the script). `vp strategy backtest SPEC
--script FILE` runs it locally; the `strategy` workflow runs it on GitHub's
machines with nothing installed. See
`docs/tutorials/your_own_strategy.md`.
