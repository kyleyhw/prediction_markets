# Forecasters

Phase 8 adds the forecasters: everything that turns a market and an
information cutoff into a probability. This page states the contract, the
look-ahead safeguard, each forecaster's reasoning, and the prompt design and
known failure modes of the LLM forecaster.

## Contract

`vp.forecast.Forecaster` is a protocol: a `name` and
`forecast(market, evidence) -> Forecast | None`. The `Forecast` carries the
probability $\hat p$ of the market's **first outcome**, the rationale, the
cost in dollars and the cutoff it was made at. `None` means the forecaster
declines the market (no price at the cutoff, an unparsed question, too little
evidence); the backtest records a skip, never a default guess.

Probabilities are clipped to $[0.01, 0.99]$ so the log score is finite and one
confident miss cannot dominate a mean.

## The Look-Ahead Safeguard

A forecaster never receives the cutoff as a number to check itself against.
It receives an `Evidence` object constructed with the cutoff, and every read
goes through it:

| Accessor | What it serves | Cutoff rule |
| :--- | :--- | :--- |
| `price_at(market)` | Last stored price of the first outcome | Point timestamp $\le t$ |
| `results(domain)` | Settled match results | Settlement time $< t$ |
| `daily_highs(city)` | Realised daily maximum temperatures | Observation date $< t$ (calendar day) |

The evidence source is the resolved dataset itself. Polymarket's resolutions
are results: a resolved match market names the winner and carries the
venue's closing time; a resolved daily-temperature event settles exactly one
bucket Yes, and that bucket's bounds are the observation. This is complete
for every market the backtest scores, free, and cannot leak, because the
settlement time is part of every record and the cutoff is enforced on the
same clock the labels use. Its limits: a team has results only where the
venue listed its matches, and a temperature is known to its bucket (one
degree in the current markets, two in the 2025 ones), not the reading.
External sources (Open-Meteo's archive for station observations, its
previous-runs endpoint for numerical-weather-prediction output as it stood
before the cutoff) were assessed on 2026-09-13: the forecast and geocoding
endpoints answer, but the archive and previous-runs endpoints returned
"daily API request limit exceeded" from the development container's shared
address, so they are not wired in; the accessor design admits them later
without touching the forecasters.

## Baselines

- **market**: the market's own price at the cutoff, $q$. Every other
  forecaster is scored against it; skill is a better proper score on the
  same markets.
- **constant**: 0.5. Anchors the scale: a Brier score of 0.25 is what
  knowing nothing earns.
- **climatology** (weather): the empirical frequency of the question's bucket
  among realised highs at the same city within 15 calendar days of the
  target date in earlier years, with Laplace smoothing $(h + 1)/(n + 2)$.
  With no earlier year it falls back to the last 14 days before the cutoff,
  which is closer to persistence than climatology and is labelled as such in
  the rationale. Below five observations it declines.

## Statistical: Elo

For `match` markets. Results before the cutoff are replayed in settlement
order from 1500 with $K = 32$; the first-listed team gets a home advantage
$H$ of 60 points in EPL and 0 in CS2. The expected score
$E_A = 1/(1 + 10^{(R_B - R_A - H)/400})$ mixes wins and draws, so with the
empirical draw rate $d$ among the fitted results the forecast for "A wins"
is $E_A - d/2$, for a draw market $d$, and for CS2, which cannot draw,
$E_A$. A team with fewer than three results before the cutoff makes the
forecaster decline. $K$ and $H$ are conventional, not fitted: fitting them
on the resolved set the backtest scores would be a leak of its own.

Per-map CS2 markets are forecast from series Elo (the map field is ignored
for rating, and map markets are not used as results), which is a known
weakness: map win rates are noisier than series win rates.

## The LLM Forecaster

`vp.forecast.llm.LLMForecaster` elicits a probability from a Claude model
through the official SDK. The design follows Vibe-Trading's principle that
the model should reason over retrieved evidence rather than from memory:

1. **System prompt** states the role, the cutoff discipline (use only what
   was public before the cutoff, and when unsure whether something is from
   after it, do not use it), and asks for the probability of the first-named
   outcome with a short evidence-based rationale, avoiding round-number
   anchors.
2. **User turn** carries the cutoff, domain, event title, question, the two
   outcome names, the end date and the parsed fields. The market price is
   never shown: a model that sees $q$ tends to return $q$, and the question
   the project asks is whether the model has information the price does not.
3. **Tools** are the evidence accessors, cutoff-bounded by construction:
   `team_results`, `head_to_head` and `daily_highs`. The loop is the plain
   Messages API tool loop (request, execute tool calls, append results,
   repeat), capped at six rounds.
4. **Output** is enforced as JSON `{probability, rationale}` by the API's
   structured output, so no parsing heuristics are needed.
5. **Cost** is computed per call from token usage at a price table
   (`PRICES`, dollars per million tokens) and summed into the forecast.
   With `samples > 1` the elicitation is repeated and probabilities averaged.

The model defaults to `claude-opus-5` at `effort: medium`. The client is
injectable, so the loop is tested offline against a fake that plays the
model; a run without credentials fails at construction, not mid-backtest.

**Known failure modes**, from Vibe-Trading's experience and the literature
on LLM forecasting, to be measured rather than assumed:

- *Memory leakage*: the model may know the outcome from training data that
  post-dates the cutoff. The prompt forbids it, the tools cannot enforce it,
  and Phase 10's leakage check (forward scores against backtest scores) is
  the measurement.
- *Anchoring*: probabilities cluster on 0.5, 0.6, 0.7. The reliability
  diagram shows it as sparse bins.
- *Overconfidence on salient teams* and *underuse of evidence*: the
  rationale hash in the registry lets identical rationales across markets
  be counted.
- *Cost*: each elicitation is two to four calls; the report prints dollars
  per forecast so a domain can be budgeted before a full run.

## Registry

`vp.forecast.registry.Registry` appends one JSON line per forecast, with the
SHA-256 of the rationale alongside the rationale itself, and is never
rewritten. It is the record of what was believed at each cutoff, for both
the backtest and paper trading.

## Choosing a Forecaster

`make_forecaster(name, domain)` builds `market`, `constant`, `climatology`,
`elo` or `llm`. The parsed subsets they apply to, from the 2026-09-13
resolved sets: 2,482 EPL match markets, 25,293 CS2 match and map markets,
131,262 weather daily-temperature markets; props (over/under, handicaps,
exact scores) have no fields and are declined by every forecaster except
`market` and `constant`.
