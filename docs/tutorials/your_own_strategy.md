# Your Own Strategy, on Your Own Copy

The [demo](https://kyleyhw.github.io/prediction_markets/) runs strategies
made from a sentence or a form. On your own copy of the project you can go
further: have any AI write the forecasting part as a short Python script,
backtest it on every past market, and change anything. It is free. There
are two ways; the first needs nothing installed.

## On GitHub, with nothing installed

1. **Make your copy.** Sign in to GitHub, open
   <https://github.com/kyleyhw/prediction_markets> and press *Fork*.
2. **Turn on its Actions.** In your copy, open the *Actions* tab and press
   the green button that enables workflows.
3. **Write the strategy with your AI.** Open
   [`strategies/README.md`](../../strategies/README.md) in your copy and
   give it to your AI (paste it, or attach it) with your idea, for example:
   "Write forecast.py for this: a team that has won three matches in a row
   is more likely to win its next one than the price says." Ask for
   `forecast.py` and, if you have no strategy from the demo, a
   `strategy.json` like [the example](../../strategies/example/strategy.json).
4. **Add the files.** In your copy, open `strategies`, choose *Add file*,
   *Create new file*, name it `mine/forecast.py`, paste, and commit. Do the
   same for `mine/strategy.json` (or upload the file the demo downloaded).
5. **Run it.** *Actions*, *strategy*, *Run workflow*: type
   `strategies/mine/strategy.json` and `strategies/mine/forecast.py`, then
   *Run workflow*. The first run fetches the past markets (up to half an
   hour); later runs reuse them. Open the finished run: its summary is the
   report, and *backtest* under *Artifacts* has every forecast.
6. **Read the report.** The script's Brier score is next to the market's:
   lower is better, and the market is hard to beat. Profit on past markets
   is luck until the forecast beats the market's score on many of them.

If the script asks an AI model for each forecast (see
[`strategies/example_ai/`](../../strategies/example_ai/forecast.py)), add
your key as a secret: *Settings*, *Secrets and variables*, *Actions*, *New
repository secret*, named for the provider (`GEMINI_API_KEY`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` or
`GROQ_API_KEY`), and the model as a variable named `VP_MODEL`, such as
`gemini:gemini-3.1-flash-lite`. Set *at most this many past markets* to 20
for the first run: each market is one call to your model.

Your copy also gets its own demo: *Settings*, *Pages*, *Source: GitHub
Actions*, then run the *pages* workflow.

## On your computer

You need Python's `uv` (<https://docs.astral.sh/uv/>) and Git.

```bash
git clone https://github.com/<you>/prediction_markets
cd prediction_markets
uv sync
uv run vp build-dataset --domain epl --histories 600
uv run vp strategy backtest strategies/example/strategy.json --script strategies/example/forecast.py
```

Coding assistants that work in a folder (Claude Code, Codex, Cursor, Copilot
and others) can read `strategies/README.md` themselves: ask for a new
strategy under `strategies/` and to run the command above.

To run the whole app on your computer, with paper trading and the strategy
assistant on any model, see [Run your own copy](run_your_own.md).
