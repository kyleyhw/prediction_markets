# Test Report: The Static Demo and the Fork Harness

Date: 2026-10-13. Environment: Python 3.14.7 via `uv`, Node 22.22 (for the
parity tests), Chromium through Playwright. Design: `docs/demo.md`.

## Purpose

The owner asked for a quick proof of concept before the hosted platform:

- a demo on GitHub Pages where a strategy can be described to an AI or
  built, run on past markets, and downloaded with its conversation, with
  nothing saved;
- forks that let people have their own AI write a strategy script, with a
  harness to run it;
- everything free.

## Checks

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .`, `ty check` | passed | 3 s |
| `pre-commit run --all-files` | all hooks passed | 4 s |
| `pytest -q` | 393 passed (383 before) | 57 s |
| `vp site` | 91 pages, no broken link | 2 s |
| axe-core 4.10.2, WCAG 2.0 to 2.2 A and AA | 0 violations, at the start and with results shown | under 1 min |

`tests/test_demo.py` runs the page's engine (`pages/engine.js`) in Node
against the Python engine on the same inputs:

- **Backtest:** six specs (edge rules with Elo and a constant belief,
  sides, price bands, dollar caps, follow rules for the favourite and the
  underdog, words, field filters, props) on 80 synthetic markets with
  fees stated and assumed. The two engines must agree on every bet,
  stake, profit, fee and Brier score to 1e-9. The first run differed in
  the seventh significant figure on Elo, because the export rounded
  forecasts to six decimals. It now exports them unrounded.
- **Checks and words:** sixty random specs across every domain, plus
  closed-shape and bound violations. The two engines must agree on the
  defaults filled in, every problem sentence and every rendered sentence.
- **The harness:** a script's answer is the belief and is recorded with
  its reason, and an answer outside 0 to 1 is refused.

## On Real Data

The datasets were built here: `vp build-dataset --histories 400` for every
domain.

- **Export:** `vp demo` exported 293 EPL and 35 CS2 markets with prices,
  while the weather and CS2 histories were still being fetched, in 39 s
  and under 300 KB. The daily build on Actions fetches 600 histories per
  domain and keeps them between runs.
- **Harness:** `vp strategy backtest strategies/example/strategy.json
  --script strategies/example/forecast.py` scored 148 EPL matches in 3.4
  s.
  - The recent-form script's Brier score was 0.2182, against the market's
    0.2152 (skill −0.014).
  - Its simulated 111 bets returned +40% with a 95% interval on the
    per-bet Sharpe ratio of [−0.08, 0.28].
  - That is luck until the forecast beats the market's score, which the
    report and the guide both say.

## In the Browser

The built site was served locally and driven in Chromium. There is no key
here, so Google's API was answered in the browser with recorded answers,
which also captured the request the page sends.

- **The form:** a strategy built from the form runs and shows its bets,
  balance, fees and skill.
- **The conversation:**
  - The model's question offers its choices as buttons.
  - Its strategy is shown in the engine's own words, then runs.
  - Both downloads hold the conversation, the spec and the results.
- **The request to Google:** the key goes in the `x-goog-api-key` header,
  the schema is sent with no `$ref`, and the turns go as user, model, user.
- **Phone width:** no page scroll sideways at 390 px.

Faults found and fixed:

1. **Model address required for Gemini.** The model form asked for an
   address on Gemini, which has none, so it never submitted. Only a typed
   OpenAI-compatible address needs one.
2. **Wrong strategy run.** A strategy built from the form was added to
   the conversation, so "Run it" on the AI's strategy ran the form's.
3. **Idea lost.** The conversation then treated the form's strategy as the
   one it was refining, which lost the person's idea. The chat now
   refines only its own strategies, and the idea is the person's first
   message.
4. **Default market group.** The form opened on the domain with the fewest
   markets. Domains are now ordered by market count.

## Not Verified

- **No real model call yet.** No real model has answered the page; the
  first visitor with a Google key is the test. Whether Google accepts the
  compiler's schema as `responseJsonSchema` is the open question. If it
  refuses, the page shows Google's message.
- **The workflows have not run on GitHub.** `pages.yml` and
  `strategy.yml` run on the next push. Pages must be enabled once in the
  repository's settings (Source: GitHub Actions) before `pages.yml` can
  publish.
- **Anthropic and OpenAI-compatible calls untested in the browser.** Their
  request shapes follow `vp/llm/`, but they were not stubbed and driven in
  the browser as Google's was.
