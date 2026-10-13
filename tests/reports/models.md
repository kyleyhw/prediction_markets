# Test Report: Any Model, the Free Demo, and Your Own Copy

Date: 2026-10-13. Environment: Python 3.14.7 via `uv 0.12.18`, Postgres 16,
Chromium through Playwright. The platform ran as local processes: `vp
serve`, three `vp worker` pools and real market data from the venue. A
small local model stood in for the free demo: llama.cpp's Python server
0.3.36 serving Qwen 2.5 1.5B Instruct (Q4_K_M, 1.1 GB) on 4 CPU cores.
The design is `docs/models.md`.

## Purpose

The owner asked for three things:

- Any model plugs in.
- The demo is free, and the owner pays nothing.
- Anyone the free demo may not serve is told so, with what they can do
  instead, including running their own copy with their own model or
  script.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 2 s |
| `pre-commit run --all-files` | all hooks passed | 4 s |
| `pytest -q` | 382 passed (360 before this work) | 52 s |
| `vp site` | the new pages build with no broken link | 2 s |
| axe-core 4.10.2, WCAG 2.0 to 2.2 A and AA | 0 violations on 44 renders | 4 min |

The axe audit covers 11 pages at two sizes (phone and laptop) and in both
reading levels. Its one finding, a glossary term smaller than 24 px, was
fixed. The new tests:

- `test_llm_providers.py`:
  - a forecast on an OpenAI-compatible server, faked, with its tool round;
  - the one-time repairs for `max_tokens` and `json_schema`;
  - errors that name the problem but not the key;
  - the address check (public `https` only, except on your own copy);
  - a program as the model, and the example program forecasting a match;
  - the presets and the free tier's countries;
  - `provider:model` on the command line.
- `test_llm_gemini.py`: Gemini's request shape, as Google's official SDK
  sends it (captured), thought signatures sent back as received, ids,
  stop reasons, retries and the free tier's $0.
- `test_platform_llmops.py`:
  - any provider stored as a workspace's own model;
  - the demo, but only after the person states a country, and only there;
  - the daily allowance per workspace and across the platform, which only
    the function can change;
  - the platform's daily cap for a paid demo.
- `test_platform_work.py`:
  - `/api/model`, where the key never comes back;
  - a connection the model refuses is not saved;
  - the demo's 428 (country needed) and 451 (region blocked) with their
    reasons;
  - estimates on the free demo and on an own key.
- The tests for the simulated users' faults: listed in the Phase 14
  report's section on the sessions.

## The Demo Path, End to End

Measured through the platform's web service with the local model as the
demo and the country rule forced on (`VP_DEMO_REGION_RULE=true`):

| Step | Answer |
| :--- | :--- |
| a strategy described with no country set | 428, "say which country you are in" |
| country Germany | 451: "Google's terms do not allow its free AI service to be used for people in the European Economic Area, Switzerland or the United Kingdom", plus both ways forward |
| country United States | 202; the compiler's two model calls answered in 5 min 4 s as valid JSON; 2 of 60 demo calls used |
| the same with Gemini on Google's free tier | not run: there is no Google key here |

On 4 CPU cores the local model reads about 58 tokens a second and writes
about 14. A compiler turn is about 3,000 tokens in, so its speed is the
machine's, not the platform's. A 1.5B model is also too small to write a
good strategy spec: the simulated users' strategies never reached a
read-back. That says nothing about the interface, which is what they were
there to test.

## Faults Found Running It

1. **Tools ignored.** The local server ignored the tools unless
   `tool_choice: "auto"` was sent. That is OpenAI's own default, so it is
   now sent with every request that has tools.
2. **Null content refused.** The server refused `content: null` on an
   assistant turn that only calls tools. It is now sent as an empty
   string, which OpenAI also accepts.
3. **`json_schema` refused, with a 500.** The server answers a request it
   cannot validate with a 500, not a 400, so the repair now triggers on 400,
   422 and 500 when the error names the response format.
4. **Answers padded to the token limit.** With the bare `json_object`
   fallback, the model could fill its answer with whitespace up to the
   8,000-token limit, about ten minutes a call. Now a server that refuses
   `json_schema` is first asked for `json_object` holding the schema,
   which llama.cpp's servers enforce, and for bare `json_object` only
   after that.
5. **Refused jobs retried.** A strategy turn the demo refused, because of
   where its author is, was retried three times. Migration 0033 adds
   `JobRefused`: such a job ends dead at once, with its reason.

## Not Verified

- Google's API has not been called. The first session with a key should
  run one demo backtest and one compiler turn, and record whether Google
  accepts the compiler's schema.
- Gemini's free-tier limits per day are shown in AI Studio, not published.
  The daily allowance defaults to 400 calls and should be set from AI
  Studio's figure.
- `deploy/run-your-own.sh` was not run: there is no Docker here. Its parts
  were tested separately:
  - the Compose settings it writes;
  - the sign-in link shown on a personal copy;
  - the program-as-model path.
