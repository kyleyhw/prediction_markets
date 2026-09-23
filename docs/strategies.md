# Strategies from Conversation

Phase 15's design. A person describes a strategy in a sentence, reads back
exactly what will run, sees what it would have done and what it costs, runs
it in paper, and watches it, with every number traceable to the engine
(plan, Phase 15, "done when"). This page fixes the four things the plan
asks for before any code: the spec, the sizing defaults, what a prompt may
override, and the number gate. It also fixes the model tiers and the
lifecycle. Everything here was decided on 2026-09-23 as proposed in the
plan's decisions table (Phase 15 rows, flags F6 to F8).

## The Idea in One Paragraph

The model is a translator, never the strategy. What a person says is
compiled into a **spec**: a small, typed JSON document that says which
markets, which belief, when to trade, how much, and when. The spec is data,
not code. It is rendered back into plain language by a deterministic
function (not by the model), so that the words the person confirms are a
function of the spec that runs and nothing else. The backtest, the paper
loop and the run card read the spec; the model never touches a number on
the way. A spec, once confirmed, is an immutable version with a hash;
refinement makes a new version and shows the difference.

## The Spec, Version 1

Every field has a default, so the smallest valid spec names only a domain.
Unknown fields are refused, which is what "a constraint is never silently
dropped" means for the compiler: anything a person asks for that the spec
cannot say becomes a refusal or a question, not an omission.

```json
{
  "version": 1,
  "name": "Arsenal at home, Elo",
  "idea": "Back Arsenal when the ratings like them more than the market does",
  "selector": {
    "domains": ["epl"],
    "kinds": ["match"],
    "where": [{"field": "side", "op": "is", "values": ["Arsenal FC"]}],
    "words": [],
    "exclude_words": [],
    "min_volume_usd": null,
    "min_liquidity_usd": null,
    "max_spread": null
  },
  "belief": {
    "forecaster": "elo",
    "instructions": "",
    "tier": "standard",
    "samples": 1,
    "sees_price": false
  },
  "rule": {
    "kind": "edge",
    "min_edge": 0.03,
    "sides": "both",
    "follow": null,
    "price_min": 0.0,
    "price_max": 1.0
  },
  "sizing": {
    "kelly_fraction": 0.25,
    "max_fraction": 0.05,
    "flat_fraction": 0.01,
    "max_stake_usd": null,
    "max_open": null,
    "max_per_event": null,
    "initial_cash": 1000.0
  },
  "schedule": {"hours_before_close": 24.0, "cadence_hours": 1}
}
```

### Selector: which markets

- `domains`: one or more domain names. They are checked against the
  registered domains, never a fixed list, so a new domain is available to
  specs when it is registered (the plan's rule against hard-coding the
  three).
- `kinds`: parsed kinds, from the domain's own list (`Domain.kinds`, also
  in its domain pack). Empty means the domain's main contracts: match
  results, winners, temperature buckets. Props (below) are opted into by
  name; they are never picked up by an empty list, because a strategy
  written for match results must not start trading corner counts because
  the parser learnt to read them.
- `where`: filters on parsed fields: `is`, `is_not` and `contains` compare
  case-insensitively with any of the values; `at_least` and `at_most` take
  one number (a bucket's `low`, a total's `line`). A field that the kind
  does not have makes the filter false, and a field no selected kind has is
  refused when the spec is validated.
- `words`, `exclude_words`: the question must contain one of `words` (if
  any) and none of `exclude_words`.
- `min_volume_usd`, `min_liquidity_usd`, `max_spread`: floors and a ceiling
  read from the live book. **They apply in paper only.** A resolved record
  carries its volume and liquidity at the end of its life, which a backtest
  must not see at the cutoff, and there is no archived book to read a
  spread from; the backtest ignores them and the rendering says so. (Phase
  17's archive of quotes can lift this.)

### Belief: where the probability comes from

- `forecaster`: a registered forecaster name (`market`, `constant`,
  `climatology`, `elo`, `llm`; Phase 16 adds signals, blends and
  committees under the same field). Validated against the registry, not a
  list in this page.
- `instructions`, `tier`, `samples`, `sees_price`: only for `llm`.
  `instructions` is the person's own guidance, added to the domain pack in
  the forecaster's prompt; it is shown verbatim in the rendering. `tier`
  picks the model (below). `samples` is 1 to 5 independent elicitations
  averaged.
- `sees_price` (default false). Whether the LLM forecaster is told the
  market's price at the cutoff. **Decided: only as an explicit belief
  option, never by default** (F7). A run whose belief saw the price carries
  that label on its run card and is left out of skill rankings, because
  its skill against the market measures anchoring, not information.

### Rule: when to trade

- `kind: "edge"` (default): trade when the belief's probability beats the
  effective price (fee included) by at least `min_edge`, on the side with
  the edge; `sides` may restrict that to `yes` (the first outcome) or `no`.
- `kind: "follow"`: **no belief at all**; buy the `follow` side
  (`favourite` or `underdog`, by the price) whenever its price lies in the
  band, at a flat stake. This is how "fade the long shots" is said honestly:
  the rendering calls it "follows the market's own prices; makes no
  forecast", and the run card scores it as P&L only, since its forecast is
  the market's by construction. (The Phase 9 report found the constant
  baseline's +97% at 24 hours to be exactly such a fade, with an interval
  including zero and a reversal at 2 hours.)
- `price_min`, `price_max`: the band the side's quoted price must lie in.

### Sizing: how much

Fractional Kelly on the belief, as the engine has done since Phase 9
(`docs/sizing.md`), with the caps the plan asks for:

| Field | Default | Meaning |
| :--- | ---: | :--- |
| `kelly_fraction` | 0.25 | fraction of the full Kelly stake |
| `max_fraction` | 0.05 | at most this share of the balance on one position |
| `min_edge` (in `rule`) | 0.03 | the smallest edge after fees worth a position |
| `flat_fraction` | 0.01 | a follow rule's stake, as a share of the balance |
| `max_stake_usd` | none | at most this many dollars on one position |
| `max_open` | none | at most this many open positions |
| `max_per_event` | none | at most this many open positions in one event |
| `initial_cash` | 1000 | the paper account's play money |

`max_open` and `max_per_event` apply in paper, where positions overlap.
The backtest's simulator settles each bet before the next (docs/sizing.md),
so they cannot bind there; the preview says so. Per-event caps are counts,
not exposure: F6 records that several positions in one event can together
exceed what the 5% cap suggests until Phase 20 sizes them jointly.

### Schedule: when

- `hours_before_close` (default 24): the backtest forecasts each market
  this long before it settled; paper trades a market from the first cycle
  inside this window before its scheduled end, so the two see the market at
  comparable distances from the end. (Backtest time is measured to the
  settlement, paper time to the venue's `endDate`; for a match the two
  differ by the match's length plus the oracle's delay, and the leakage
  check compares like with like.)
- `cadence_hours` (default 1): how often the paper cycle runs, 1 to 24.

## What a Prompt May Override

**Decided (F6): a prompt may lower any risk setting and raise none.** The
defaults above are also the ceilings for a prompt: `kelly_fraction` ≤ 0.25,
`max_fraction` ≤ 0.05, `flat_fraction` ≤ 0.01 and `min_edge` ≥ 0.03, and
`max_stake_usd`, `max_open`, `max_per_event` no looser than the
workspace's own caps (`Caps`, set by a workspace owner, never by a prompt).
A spec over a cap is refused by validation, whoever wrote it; the compiler
turns the refusal into a question ("the most a strategy may stake on one
market is 5%; use 5%?") rather than quietly lowering it. Everything else is
free to set: which markets, which belief, the band, the side, the schedule.

## The Rendering and the Diff

`render(spec)` returns plain sentences, one per part, deterministic and
tested for every field. It is what the person confirms, what the strategy
page shows and what a run card quotes. It uses the domain's title and the
kinds' plain names, formats money and chances the way the interface does
(cents for prices, dollars for stakes), and states the paper-only fields as
paper-only. Its English lives beside the spec in the engine, because it is
part of the spec's contract (a change of wording is reviewed like a change
of behaviour); the interface's catalogue holds everything around it.

`diff(old, new)` lists the changed fields as paths with both values and
the rendered sentences that changed, which is what refinement shows.

## Versions and Hashes

A spec version is the canonical JSON (keys sorted, no spaces) and its
SHA-256. Versions are never edited: a refinement, a rename, a new cap is a
new version whose parent is the old one. Every backtest, paper account and
run manifest records the hash of the version it ran, so a number on a run
card can be traced to the exact words that were confirmed.

## Props (Task 51)

The venue labels every sports market with a type (`sportsMarketType`,
measured on 2026-09-23 across the Premier League and Counter-Strike tags):

| Domain | Types seen |
| :--- | :--- |
| Premier League | `moneyline`, `totals`, `spreads`, `soccer_team_totals`, first- and second-half totals, team totals and spreads, `soccer_exact_score`, `soccer_first_half_exact_score`, `soccer_halftime_result`, `soccer_second_half_result`, `both_teams_to_score` (and per half), `soccer_anytime_goalscorer`, first to score (and per half), total corners, team corners, corners per half, `soccer_game_corners_odd_even`, `soccer_first_corner` |
| Counter-Strike | `moneyline`, `child_moneyline` (a map's winner), `totals` (maps played), `map_handicap`, `round_over_under_game_N`, `round_handicap_game_N`; odd/even kills and rounds per map in earlier captures |

The record now stores the venue's type (`market_type`) and the market's
resolution text (`description`), and a shared prop parser reads the
questions into kinds with fields: `total`, `team_total`, `spread` (which
includes the esports handicaps, with `stat` saying maps or rounds),
`exact_score`, `halftime_result`, `second_half_result`,
`both_teams_to_score`, `anytime_scorer`, `first_to_score`, `first_corner`,
`odd_even`; fields
`period` (`full`, `1st_half`, `2nd_half`, `map_N`), `stat` (`goals`,
`corners`, `maps`, `rounds`, `kills`), `line`, `team`, `score_a`,
`score_b`, `player`, and the fixture's `team_a` and `team_b` from the event
title. The parser reads the question, and its tests check it against the
venue's own label on the captured questions, so a disagreement between the
two is a failing test rather than a silently wrong kind. A market's
resolution text is shown on its page: for a prop, the rules (what counts as
a corner, extra time, a void match) are the contract, and a person should
read them before trusting a forecast.

Found while measuring: the Premier League's keyword `epl ` admitted Dota 2
"EPL Masters" and "EPL World Series" series and a Kerala cricket league;
the domain now excludes `dota` and `t20`.

## Model Tiers

**Decided (F8): a cheap tier for breadth, the expensive tier on demand.**
Two tiers for the LLM forecaster, identifiers chosen from the provider's
current list at build time and kept in one table (`vp/forecast/llm.py`):

| Tier | Model | Price per million tokens (in, out) | Use |
| :--- | :--- | :--- | :--- |
| `standard` (default) | `claude-sonnet-5` | $2, $10 | backtests and paper at breadth |
| `strong` | `claude-opus-5` | $5, $25 | on demand, small samples |

The compiler and the research agent run on `claude-opus-5` with adaptive
thinking and the server-side refusal fallback, since what they produce is
read and confirmed by a person and a mistake there costs more than tokens;
a compile is one short call. LLM backtests default to a 100-market sample
through the batch endpoint (F8), and the preview shows the estimated cost
before anything runs.

## The Compiler (Task 52)

One call with structured output: the model answers with exactly one of

- `spec`: a complete spec (the schema above, with its `additionalProperties:
  false`), which is then validated by the engine, including the caps; a
  validation failure becomes the question the person sees;
- `question`: one clarifying question when a field is ambiguous ("which
  side of the match?"), with the choices when there are few;
- `refusal`: a request that needs something the spec cannot say ("only
  when it rains", "stop after three losses"), naming the part it cannot
  express, so it is never dropped.

The prompt holds the spec's schema, the domain packs of the domains in play
(their kinds and fields), the workspace's caps, the person's memory (task
55) and, when refining, the current spec. The model never sees a market
price or a result: compiling is translation, not forecasting.

## Preview (Task 53)

Before anything runs, from data only: the markets the selector picks now
(from the newest shared snapshot), the resolved markets it would have
picked per month (the backtest's universe), five example questions, the
estimated cost of a backtest and of a month of paper (zero unless the
belief is the LLM, then `estimate_usd` on the counts), and the power
statement: how many settled markets the selector provides a month against
how many settled bets an edge of the spec's minimum size needs to be told
from zero at the 5% level with 80% power, $n \approx (1.96 + 0.84)^2\,
p(1-p)/\delta^2$ at price $p$ (about 2,200 bets for 3 points at 50¢;
derivation in `vp/strategy/preview.py`). An LLM belief's paper cost counts
one forecast per cycle while a market is in its window, since the loop asks
again each cycle until it holds a position.

## The Number Gate (Task 54)

The research assistant's text may carry no figure that is not in a tool
result of the same turn. A draft is checked by extracting every number
(integers, decimals, percentages, money, with thousands separators and the
cents and percent forms the interface uses) and requiring each to match a
number in the turn's tool results, allowing the same number rounded to the
shown precision or rescaled between fraction and percent. A draft that
fails is regenerated once with the failing figures named; if it fails
again it is released with each failing figure replaced by "(see the data)"
and the tool result shown beside it. Figures the page shows (tables, run
cards) are rendered from data by the page, never by the model.

## Loop Guards (Task 54)

Eight tool calls without a new observation (a result not seen before in the
turn) stop the turn with a visible request; an identical call that failed
once is refused the second time; a session has token, turn and wall-clock
budgets, is cancellable, and its cost is shown as it runs.

## Lifecycle (Task 58)

`draft` (compiled, not confirmed) → `previewed` → `backtested` → `paper`
→ `retired`; `live` comes with Phase 22. Confirming a version freezes it.
Each strategy has its own paper account per version in paper, so its P&L,
skill and settled count are its own, and a refinement that goes to paper
starts a new account beside the old rather than rewriting its history.

## Fees in a Strategy's Backtest

A strategy's backtest charges each market's own taker fee, as paper does
(F5). A market whose record states a fee (including a stated zero: many
settled markets traded before the venue charged one) is charged exactly
that. A record that states nothing (datasets built before fee schedules
were captured) is charged the venue's published 2026 rate for sports and
weather, 5% of $p(1-p)$ a share, since charging nothing flatters every
strategy; the run card says how many markets that was.

## Where It Lives

- Engine: `vp/strategy/spec.py` (the spec, validation, caps, rendering,
  diff, hash), `vp/strategy/run.py` (a spec's selector and policy, its
  backtest and its paper cycle), `vp/domains/props.py`; the policy hook in
  `vp/backtest/sizing.py`.
- Platform: the `strategies` and `strategy_versions` tables, the compiler
  and research-session jobs, the strategy pages.
