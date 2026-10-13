# Models: Any Model, a Free Demo, Your Own Copy

Every model-backed feature (the strategy compiler, the research assistant,
the LLM forecaster, committees) needs a language model. This page records
how the platform connects to one, decided with the owner on 2026-10-13:

1. **Any model plugs in.** A person connects the model they want: any
   provider with an Anthropic, Gemini or OpenAI-compatible API (which
   covers OpenAI, OpenRouter, Groq, Mistral, DeepSeek, Together, xAI and
   self-hosted servers), with their own key. Nothing else in the platform
   knows which model it is talking to.
2. **The demo is free, and the owner pays nothing.** Without a model of
   their own, a person uses the platform's demo model on Google's free
   tier, within a daily allowance.
3. **Where the free tier may not be used, the person is told so plainly**,
   and offered the two ways that still work: their own model, or their own
   copy of the platform with any model (including a free one running on
   their own computer).

## How a Model Connects

`vp/llm/` is the one place that talks to providers. A *connection* is a
provider, a model and, where the provider needs them, a key and an
address. `vp.llm.connect(...)` turns a connection into a client with one
call shape, the subset of the Anthropic Messages API the callers use
(`messages.create` with a system prompt, tools, tool results and a
JSON-schema answer, answered by content blocks, a stop reason and token
usage), whatever the provider:

| Kind | Providers | How |
| :--- | :--- | :--- |
| `anthropic` | Anthropic | the official SDK, unchanged |
| `gemini` | Google | `generateContent` over REST (`vp/llm/gemini.py`) |
| `openai` | OpenAI, OpenRouter, Groq, Mistral, DeepSeek, Together, xAI, Ollama, LM Studio, llama.cpp, vLLM, any compatible address | Chat Completions over REST (`vp/llm/openai_compat.py`) |
| `command` | your own program | the request as JSON on its standard input, the reply as JSON on its standard output (`vp/llm/command.py`); only on your own copy |

The presets in `vp/llm/providers.py` give each provider its address, so
a person picks "Groq" and types the model's name, not a URL. Model names
are typed, not chosen from a list: providers add models weekly, and a
list kept here would always be behind.

A connection fixes its model: whatever the caller asks for (a strategy's
tier, the compiler's default), `resolve_model(client, model)` returns the
model the connection runs, and that name is what is priced and recorded
on every forecast and every spend row, so results from different models
are never mixed silently.

**Costs.** A model with a recorded price (`PRICES` in
`vp/forecast/llm.py`) is priced as before. A model without one is recorded
at $0 and marked unpriced; it is the person's key, so the bill is between
them and their provider. The demo is free, so it costs $0.

**What each adapter does about structure.** Function calling and a
JSON-schema answer are asked for in each provider's own terms. An
OpenAI-compatible server that refuses `response_format: json_schema` is
asked once more with `json_object` and the schema in the system prompt;
the callers validate every answer anyway (the compiler repairs, the
forecaster declines a market it cannot parse). A provider without
function calling cannot run the research assistant or the LLM forecaster;
the error says so.

### Addresses a person types

A custom address is the one place a person can make the platform's
servers send a request somewhere. On the hosted platform it must be
`https`, and every address its name resolves to must be public (not
loopback, private, link-local or otherwise reserved), checked when it is
saved and again each time a client is made; redirects are not followed.
Your own copy allows local addresses (`VP_ALLOW_PRIVATE_MODEL_URLS`, on
by default outside production), so `http://localhost:11434/v1` reaches
Ollama. The `command` kind is never offered to a person on the hosted
platform: it is set by whoever runs the copy, in its environment.

## The Free Demo

The demo is one connection the operator configures (`VP_DEMO_PROVIDER`,
`VP_DEMO_MODEL`, `VP_DEMO_API_KEY`, and `VP_DEMO_BASE_URL` for a
self-hosted server). The default is `gemini` / `gemini-3.1-flash-lite`
on Google's free tier: it is free, supports function calling with a
JSON-schema answer in one request, and the owner asked for it.

What the free tier means, from Google's terms (read 2026-10-13), and what
the platform does about each:

| Google's terms say | So the platform |
| :--- | :--- |
| On unpaid quota Google uses prompts and answers to improve its products, and human reviewers may read them | says so beside every demo answer's starting point (Settings, the guided start) and in the privacy notice: do not put anything private into the demo; your own model is covered by its own provider's terms |
| In the EEA, Switzerland and the UK, an app may serve users only through paid services | does not offer the demo to people there |
| The API is offered only in the countries Google lists | does not offer the demo elsewhere either |
| Free quota is per project, measured per minute and per day | keeps its own count of demo calls per day, platform-wide and per workspace, below the quota |
| Users must be 18 or older | already the platform's rule (task 48) |

**Where a person is.** Each person says which country they are in
(Settings, and the first time they use the demo). The platform cannot
know better without paying for a lookup, and self-attestation is already
the rule for live trading's jurisdiction check (F1). The allow-list is
`FREE_TIER_COUNTRIES` in `vp/llm/providers.py`: Google's list of
available countries without the EEA, Switzerland and the UK. It applies
only when the demo is Gemini's free tier; a demo on any other connection
(a copy running its own model) has no region rule.

**The message.** A person in a blocked country who asks for something
model-backed is told, in those words, that the free demo model is not
available where they are, why (Google's free tier may not serve their
country), and what still works: connecting their own model in Settings,
or running their own copy with their own model (or their own script),
for free, on their computer ([the guide](tutorials/run_your_own.md)).
Everything that needs no model (markets, backtests of statistical
forecasters, signals, paper trading of the sample strategies) works as
before.

**The allowance.** Every demo call takes one unit from today's count
(midnight UTC) before it is made: `VP_DEMO_DAILY_CALLS` across the
platform (400 by default, set from the quota AI Studio shows) and
`VP_DEMO_WORKSPACE_DAILY_CALLS` per workspace (40), so one keen person
cannot use up everyone's day. A model-backed job is refused up front when
its estimated calls do not fit in what is left, and a call that finds
the allowance gone stops the job with a message saying so. The answer to
an exhausted Google quota (429 `RESOURCE_EXHAUSTED`) gets the same
message. Calls on a person's own model count against nothing here.

## Your Own Copy

For anyone the demo cannot serve, or anyone who wants to run their own
script, the repository runs on one computer with the same interface:
`deploy/run-your-own.sh` creates the settings, builds the image and
starts it with Docker; it asks which model to use (a free local model
through Ollama, a key from any provider, or a program of their own). On a
copy whose address is the computer itself, the sign-in page shows the
sign-in link instead of emailing it, since there is no mail server and
nobody else can reach the page. The guide is written for people who have
not used a terminal before: [tutorials/run_your_own.md](tutorials/run_your_own.md).

This changes flag F9 in one respect: running a copy remains a
developer's path for everything else (its archive starts empty and its
sources' terms are its runner's), but it is now offered to people as the
way to use a model the hosted demo cannot serve.

## What Is Unverified

Google's API has not been called from here: there is no key. The
OpenAI-compatible adapter was run end to end against a real local server
(llama.cpp with a small Qwen model, 2026-10-13): the compiler, the
research assistant and an LLM backtest, through the platform; see
`tests/reports/models.md`. The first session with a Google key should
run one demo backtest and one compiler turn and record whether Google
accepts the compiler's schema.
