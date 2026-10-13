# Models: the Demo Model and Your Own

Every model-backed feature (the strategy compiler, the research assistant,
the LLM forecaster, committees) needs a language model, and someone pays
for each call. This page records how the platform chooses the model and
who pays, decided on 2026-10-13. The owner's requirements: anyone can try
the model-backed features without bringing a key, nobody else's use can
run up the owner's bill, and anyone who wants a stronger model can plug
in their own key, Claude Fable 5.1 for example.

## The Decision

Two routes, chosen per workspace for each job:

| Route | Who pays | Model | Limits |
| :--- | :--- | :--- | :--- |
| **Own key** | the person, billed by Anthropic | the person's choice (Fable 5.1, Opus, Sonnet, Haiku), or the strategy's tier | none from the platform; the provider's own |
| **Demo** | the platform | `gemini-3.1-flash-lite` (`VP_DEMO_MODEL`) | the workspace's monthly budget, the platform's daily cap, and the Google project's spend cap |

The platform's key is Google's (`VP_GEMINI_API_KEY`). If only an
Anthropic platform key is set (`VP_ANTHROPIC_API_KEY`), the platform pays
for Claude as before. When both are set, the demo model wins, so a
deploy cannot start paying Claude prices by accident.

## Why Gemini Flash-Lite, Paid Tier

Prices per million tokens, from Google's pricing page on 2026-10-13:

| Model | Input | Output | Structured output with tools |
| :--- | ---: | ---: | :--- |
| Gemini 2.5 Flash-Lite | $0.10 | $0.40 | no (Gemini 3 only) |
| **Gemini 3.1 Flash-Lite** | **$0.25** | **$1.50** | yes |
| Gemini 3.5 Flash-Lite | $0.30 | $2.50 | yes |
| Claude Haiku 5.5 | $0.10 | $0.50 | yes |
| Claude Fable 5.1 | $10 | $50 | yes |

One LLM forecast is about three rounds of 1,500 tokens in and 600 out
(`vp/forecast/llm.py`), so a demo forecast costs about $0.004. A 50-market
demo backtest is about 20 cents, and $1 a day buys about 250 forecasts or
a hundred compiler turns. The forecaster needs function calling and a
JSON-schema answer in one request; Google supports that only on Gemini 3
models, which rules out 2.5 Flash-Lite.

Claude Haiku 5.5 is as cheap and would need no adapter, but the owner
asked for a demo model that does not draw on their Anthropic account.
Changing `VP_DEMO_MODEL` and the key is all a switch would take.

**The free tier is not usable**, for three reasons in Google's terms
(read 2026-10-13):

1. On unpaid quota, Google uses prompts and answers to improve its
   products, and human reviewers may read them. The privacy notice
   (`vp/platform/legal.py`) promises that nobody uses a person's
   strategies or prompts to train models.
2. An app may serve users in the EEA, Switzerland or the UK only through
   paid services. The first region is Amsterdam, and the users are
   expected to be European.
3. The free quota is per project and small, roughly hundreds of requests
   a day, so one keen person would use up the demo for everyone.

On the paid tier, Google does not use prompts to improve its products.
At the prices above, the spend caps below keep the cost close to free.

## Three Walls Against a Runaway Bill

1. **The workspace's monthly budget** (`budgets.py`, $5 by default, set
   per workspace with `vp admin budget`). Every job that spends reserves
   its estimate first, priced at the model that will actually run, so a
   demo estimate is the Flash-Lite price, not Opus's.
2. **The platform's daily cap** (`VP_PLATFORM_DAILY_USD`, default $2). A
   reservation is refused (402) when the platform-paid spend since
   midnight UTC across all workspaces, reservations included, would pass
   it. The check runs under one global lock, so concurrent starts cannot
   both fit in the last cent. Paper cycles that ask a model check it too.
   This wall stops many new accounts from each spending their $5.
3. **Google's project spend cap**, set in AI Studio (billing, project
   spend cap) to a monthly figure such as $30. Google enforces it about
   ten minutes late, so it is the last wall, not the first.

Calls on an own key count toward none of these.

## Own Keys and the Model Choice

An own key is an Anthropic key, sealed as before (`llmops.py`). A person
may also choose the model it runs (Settings → Your model key): any Claude
model with a recorded price. Without a choice, a strategy's tier decides:
`standard` is Sonnet 5 and `strong` is Opus 5. The choice is stored on the
key's row (`provider_keys.model`, migration 0031) and applies to every
model call in the workspace. The model used is recorded on every forecast
and every spend row, so results from different models are never mixed
silently.

## How the Code Routes It

- `vp/forecast/gemini.py` is a client with the subset of the Anthropic
  SDK's surface the callers use: `messages.create` and
  `beta.messages.create`, taking system prompts, tools, tool results and
  a JSON-schema answer format. It answers with Anthropic-shaped replies
  (`content` blocks, `stop_reason`, `usage`). It calls Google's official
  SDK (`google-genai`), and the model's own turns go back exactly as
  received, so Gemini 3's thought signatures survive tool rounds. It has no
  batch API, so a demo backtest runs unbatched. Thinking is left at the
  model's default. Cached tokens are priced as ordinary input, which
  overstates the cost a little.
- A client can name the model it runs: `model_for(requested)`. The demo
  client always answers with the demo model, and an own key answers with
  the person's choice. The forecaster, compiler and research assistant
  call `resolve_model(client, model)` once, then price and record that
  model. The engine still knows nothing of the platform.
- `llmops.client_for(pool, principal, settings)` picks the route. With
  `GEMINI_API_KEY` exported, `vp backtest --domain epl --forecasters llm
  --model gemini-3.1-flash-lite` runs the demo model from the command line
  too.

## What Is Unverified

None of this has run against a real API: the container holds no keys.
Tests drive the adapter through a fake of Google's SDK. The first keyed
session should run `vp backtest --domain epl --forecasters market llm
--model gemini-3.1-flash-lite --max-markets 20` and one compiler turn on
the stand-in. Two things to watch for: whether Google accepts the
compiler's JSON schema as it is (the compiler repairs invalid answers,
but a schema Google rejects fails the call outright), and how good the
demo model's forecasts are, which the backtest reports like any other.
