# Phase 15 Test Report: Strategies from Conversation

Date: 2026-09-23. Environment: Python 3.14.7 via `uv 0.12.18`, Postgres 16
in the development container, Chromium through Playwright with axe-core;
`vp serve` and one worker over a local store holding the demo datasets
(built from the live venue earlier the same day); the resolved sets of the
Phase 13 stand-in (88,668 CS2, 12,716 Premier League and 134,077 weather
markets) for the parser and base-rate measurements.

## Purpose

A person describes a strategy in a sentence, reads back exactly what will
run, sees what it would have done and what it costs, runs it in paper and
watches it, with every number traceable to the engine (the plan's "done
when"). The design page came first (`docs/strategies.md`), with the
decisions of the plan's Phase 15 rows taken as proposed; then the spec,
props, packs, compiler, preview, research assistant, manifests and cards,
lifecycle, memory, evals and refinement.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |
| `pytest -q` | 285 passed (240 before the phase) | 12.5 s |

| File | Tests | What |
| :--- | ---: | :--- |
| `test_strategy.py` | 15 | the 133 captured prop questions parse to the venue's own labels; the spec is closed and bounded; a prompt may tighten risk and never loosen it; validation names what the markets cannot say; the rendering says every setting and is deterministic; hash and diff; the policy; the selector with paper-only floors; a strategy's paper cycle trades only its markets, in its window, within its caps |
| `test_strategy_compiler.py` | 7 | the compiler against a fake model: a spec rendered with the person's words and its cost; questions and refusals pass through; a spec over the caps is refused and repaired once, then becomes a question; refinement keeps the idea and shows the change; the schema is closed everywhere; every domain has a pack; the preview's counts and power statement |
| `test_agent.py` | 13 | the research assistant against a scripted model: an answer from tool results passes the gate; an invented figure is regenerated once, then replaced; no-progress, repeated-failure, time, call and session guards; cancellation; tools refuse the future; the gate reads figures as a person would |
| `test_evals.py` | 3 | each harness check can pass, fail or not apply; the held-out prompts run in CI; a wrong answer is caught |
| `test_platform_strategies.py` | 5 | a conversation becomes a frozen version only its workspace sees (the trigger refuses an edit); a backtest with manifest and card; paper by the spec in an account of its own with its manifest first in the ledger; memory is the person's; the research job answers as the person and is charged |
| `test_platform_web.py` | +2 | the routes end to end and across two people; a spec is never taken from the browser; memory and packs |

## The Spec and Props (tasks 50, 51)

The spec is five parts of closed, typed data; its rendering is five
sentences written by the engine. What a person reads for the follow rule
tried in the browser:

> Markets: Premier League, match results. Belief: none. It follows the
> market's own prices and makes no forecast. Trade: buys the favourite of
> every market only when the price is between 55¢ and 90¢. Size: 1% of the
> balance on each and never more than $20. When: from 24 hours before a
> market's scheduled end, checked every hour; a backtest forecasts each
> market 24 hours before it settled. Starts with $1,000 of play money.

Props are parsed against the venue's own `sportsMarketType`, which the
record now stores with the market's resolution text. On the resolved sets:

| Domain | Members | Main contracts | Props | Unparsed |
| :--- | ---: | ---: | ---: | ---: |
| CS2 | 87,918 | 26,115 | 59,787 | 2,016 (2.3%) |
| Premier League | 12,716 | 2,512 | 9,347 | 857 (6.7%) |
| Weather | 134,077 | 131,434 | none | 2,643 (2.0%) |

Two thirds of CS2 markets and three quarters of Premier League markets are
props, invisible to every strategy before this phase. Most of what is left
in CS2 is "Team to win 2 maps?", whose meaning depends on the series
format and is left unparsed rather than guessed; in the Premier League,
season and player questions (top scorer, managers) that no forecaster
reads. Measuring found two faults, now fixed: the keyword `epl ` admitted
Dota 2's "EPL Masters" and a Kerala cricket league, and CS2's tags admitted
750 Dota 2 series markets.

## Packs, Compiler, Preview (tasks 52, 53, 56)

The three packs are written from the venue's events and the resolved sets,
with base rates measured on them (a Premier League match's draw market
resolved Yes 26.6% of the time; an exact-score market 5.8%; a daily
temperature bucket 9.5%, about one over the number of buckets).

The compiler is one structured-output call (claude-opus-5, adaptive
thinking, the server-side refusal fallback); its answer schema is the
spec's, closed, with every field required and numeric bounds removed for
the grammar and checked by the engine instead. **It has not run against
the model**: the container holds no key (task 60). The held-out set of 24
prompts (15 specs, 3 questions, 6 refusals) runs in CI against recorded
answers; all pass the full compiler path including validation, which tests
the harness, not the model's accuracy.

Preview against what the backtest then touched, on the demo root:

| Strategy | Preview: settled markets | Backtest: selected | With a price at the cutoff | Scored |
| :--- | ---: | ---: | ---: | ---: |
| Premier League favourites, follow | 94 | 94 | 40 | 40 |
| Counter-Strike favourites, follow (48 h) | 176 | 176 | 0 | 0 |

The preview's count equals the backtest's universe; the preview's "with
price history" (94 and 0) is an upper bound on what can be scored, since a
history may not reach back to the cutoff. The demo root holds no CS2 price
histories, which the preview and the card both say.

The preview's paper cost for an LLM belief made one thing plain: the paper
loop asks the belief again every cycle while a market is in its window, so
an LLM strategy on Premier League draws (about 35 a month) would cost
about $1.35 to backtest on 100 markets and about $23 a month in paper at
the standard tier. The preview shows it; making the loop ask once per
market per window is a follow-up (below).

## Research Assistant and the Number Gate (task 54)

Tools over the data (markets open and settled, one market in full,
cutoff-bounded evidence, a spec preview, packs, glossary) and, on the
platform, the person's strategies, run cards, run comparison and a free
backtest. Against a scripted model the guards stop a turn after eight
calls with nothing new, refuse an identical failing call without running
it, and stop at the time, call and session budgets; a job's cancellation
stops it at the next step. The gate caught two faults in itself while it
was built: dates in tool results had licensed small counts ("won 1 match"
passed on "2026-03-01"), and hyphenated dates had read as negative numbers.
Dates now count as their year only.

## Manifests, Cards, Lifecycle, Memory, Refinement (tasks 55, 57, 58, 61)

Every strategy backtest writes, per domain, the spec, its rendering, a
manifest (spec hash, belief, model, pack hash, dataset version, fee
source, package versions; its hash leaves out the time) and a card; a
paper account's ledger starts with its manifest. The card is computed from
the run: for the Premier League follow rule, "40 of 94 markets scored. 39
bets, −0.3% overall, $0.00 in fees. It cannot be told apart from the
market", with four caveats (small sample, interval includes zero, a follow
rule is judged by P&L, 54 markets without a price). The $0.00 is the
records' own statement: those settled markets traded without fees. A
record that states no fee at all (the full resolved sets, built before fee
schedules were captured) is now charged the published 5% rate, and the card
counts such markets.

`vp admin evals` over the development database after the browser runs:
confirmed spec equals executed spec 3 of 3; cost reported 2 of 2; the
number gate 1 pass, 1 not evaluable (a turn that stopped early); cutoffs 2
not evaluable (no evidence call).

## In the Browser

Walked through in Chromium against `vp serve` and a worker: Strategies,
Describe (sending without a model key is refused in words: "no model key
is available for this workspace"), a proposal with a question before it,
Remember, Run this, the strategy page with its preview, a backtest to its
card, paper, Detailed, Settings with memory, dark theme; then the same on
the Premier League; then Research. axe-core (WCAG 2.0 to 2.2, A and AA):
26 renders, no violations.

## Not Done

- **Task 60, the first LLM runs**, and so the compiler's accuracy on the
  held-out prompts and the LLM skill numbers with their window split: the
  container has no API key. The first keyed session runs `vp strategy eval
  --live` (24 compiles, a few cents) and `vp strategy backtest` with an LLM
  belief on each domain (the preview prints the cost first).
- **Follow-ups found here**: the paper loop re-asks an LLM belief every
  cycle (memoise per market and window); "Team to win N maps" CS2 props;
  workspace caps are in the engine (`Caps`) but have no page to set them
  yet; the domain packs' base rates should be refreshed by a job rather
  than by hand.
