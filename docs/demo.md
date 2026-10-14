# The Demo on GitHub Pages

Decided 2026-10-13 by the owner: until the platform has a host and
sign-in, the public face of the project is a static demo on GitHub Pages,
free to run, and the full tool is each person's own copy (a fork). The
hosted platform with accounts (`docs/platform.md`) follows later and
reuses everything below.

## What a visitor can do

Three tabs; the first, the AI, is selected.

- **Describe a strategy to an AI**, in plain words, with no key: the free
  demo AI answers (below). Or with their own model and key: Google's
  Gemini, Anthropic, OpenAI, OpenRouter, Groq and the other providers in
  `docs/models.md`, or a model on their own computer. The page asks the
  model exactly what the platform's
  compiler asks (`vp/strategy/compiler.py`: the same instructions, context
  and answer schema), checks the answer as the engine does, and shows the
  strategy in the engine's own words (`render`).
- **Or build one from a form**, with no key: always back the favourite or
  the underdog, or bet when a statistical forecaster (Elo, climatology, a
  signal) beats the price by a margin.
- **Or write it as code**: a Python function, run in the browser by
  Pyodide (`pages/pyworker.js`), with typed inputs and output
  (`pages/strategy_api.py`):

  ```python
  def decide(market: Market, past: list[Result]) -> Signal: ...
  ```

  `market` is the market as it was at the chosen time before it settled
  (question, kind, fields, price, the built-in forecasts then); `past` holds
  the markets that had settled by then, with how they ended. It returns
  `"yes"` or `"no"` (a buy signal, staked flat), `None` (skip), or a chance
  between 0 and 1 (bet when it beats the price by a margin, Kelly-sized).
  The return value is checked on every call and a wrong one stops the run
  with a message naming the market; a run is stopped after a minute. The
  answers go through the same simulation as every other strategy, and the
  signal rule is in the Python engine too (`Policy(follow="signal")`), so
  the parity tests cover it.
- **Run it on past markets**: every resolved market of the chosen domains
  that has a price history, at the time before settlement the strategy
  asks for. The page shows bets, profit, drawdown, fees and the forecast's
  skill against the market.
- **Download** the strategy (JSON, the spec, or the code) and the
  conversation or code with the results (Markdown). Everything is in
  paper money. Nothing else is kept: there is no server to keep it.

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
3. **The free AI is a few lines on Cloudflare's free plan**, and otherwise
   the visitor's browser calls the model. Google's, Anthropic's and
   OpenAI-compatible APIs accept calls from a web page (Anthropic's with
   its `anthropic-dangerous-direct-browser-access` header). The key goes
   from the page to the provider only, is held in memory, and is gone when
   the tab closes.

A GitHub Action (`.github/workflows/pages.yml`) rebuilds the datasets every
day (their histories are cached between runs), exports them, builds the
documentation site into `docs/`, and publishes both. It needs Pages
enabled once: the repository's *Settings*, *Pages*, *Source: GitHub
Actions*.

## The free demo AI

Decided 2026-10-14: the demo must work with no key. A key in a static page
is a public key, so the owner's Gemini free-tier key lives in a Cloudflare
Worker (`worker/`), deployed by `.github/workflows/demo-proxy.yml`. It
costs nothing: Cloudflare's free plan allows 100,000 requests a day, and on
Google's free tier a key with no billing account stops at its daily quota
instead of being charged. The key should come from a Google project of its
own with billing never enabled, so the demo cannot use up the owner's other
work and can never cost money.

The worker is not a general chatbot on the owner's key:

- it answers only `POST /compile` from the demo's own site (and any origin
  listed in `ORIGINS`);
- it adds the compiler's instructions and answer schema itself, read from
  the published `data/demo.json`, so every answer is forced into a strategy;
- it takes at most 16 messages of 4,000 characters, and ten messages a
  minute from one address (Cloudflare's rate-limiting binding);
- it refuses, with Google's reason, people where the free tier may not
  serve them, by the country Cloudflare reads from their connection
  (`worker/countries.js`, kept equal to `vp/llm/providers.py` by a test),
  and the page then offers a model of their own;
- it says so when Google's daily quota is used up.

The page says, before anyone types, that the free tier lets Google use what
is typed to improve its products. Without the worker (a fork that has not
set it up) the page asks for a key, as before.

To switch it on, once:

1. In Google AI Studio, create a project for the demo, with no billing, and
   a key in it.
2. Create a free Cloudflare account; under *My Profile*, *API Tokens*, make
   a token from the *Edit Cloudflare Workers* template, and copy the
   account ID from the Workers page.
3. In the repository's *Settings*, *Secrets and variables*, *Actions*, add
   the secrets `GEMINI_API_KEY`, `CLOUDFLARE_API_TOKEN` and
   `CLOUDFLARE_ACCOUNT_ID`, then run the *demo-proxy* workflow.
4. Add the variable `DEMO_PROXY_URL` with the address it prints (ending in
   `workers.dev`) and run the *pages* workflow.

## What it does not do, and why

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
