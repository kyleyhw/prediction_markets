# Opening a New Domain

A domain is a family of markets a forecaster can reason about with the
same evidence: Premier League matches, CS2 series, daily temperatures. The
platform must be able to add one without touching anything but the
domain's own files (plan, task 79). `tests/test_domain_boundary.py` holds
that line: no code outside `vp/domains/` may name a domain, so the command
line, the platform, the signals and the interface all reach a domain
through `DOMAINS` and the domain's own properties.

## The kit

1. **Membership rules.** `vp/domains/<name>.py` defines a `Domain`: the
   venue's tag ids and labels, keywords, exclusions (checked first, and
   they veto), a title and a one-sentence summary in plain words (the
   interface shows them), and `kinds`, the contract kinds with the fields
   each carries. Register it in `vp/domains/__init__.py`.
2. **A parser, with recorded questions.** `parse(question, event_title)`
   reads a question into `kind` and fields. Record at least a hundred live
   questions of every form in a test before writing a pattern, and measure
   coverage on a full `vp build-dataset --domain <name> --no-history`: the
   report prints what did not parse. Props use `vp/domains/props.py`
   against the venue's own `sportsMarketType`, listed in `props`.
3. **Properties the rest of the system reads.** `home_first` (the first
   team plays at home: the rating signals add a home advantage);
   `openfootball` and `zone` (results from openfootball, dated in the
   league's time); `observes` follows from a `daily_temperature` kind.
   A new property is added to `Domain` with a default, never as a list of
   names elsewhere.
4. **Evidence.** Say which accessors answer for the domain
   (`docs/evidence.md`): results from its own resolved markets always; an
   archive source only once its terms are recorded on that page (F9).
5. **Signals.** A signal applies by kind, so a `match` domain gets the
   rating signals and a football one the goals models without a line of
   code; run `vp signals bench --domain <name>` and attach the result.
6. **A domain pack.** `vp/domains/packs/<name>.md`: what the markets are,
   how they resolve, the evidence and its limits, in the pack format the
   compiler and the research assistant read (`docs/strategies.md`).
7. **Tests.** The parser test with the recorded questions; the boundary
   test passes; `tests/test_domain_kit.py` shows the pattern: a domain
   defined only by its adapter reaches the strategy spec, the signals and
   the evidence.

Nothing else changes: `vp build-dataset`, `vp snapshot`, `vp backtest`,
the market-data service, the evidence collectors, the Signals page and the
strategy spec all take the domain from `DOMAINS`.

## Candidates

Counted on the venue on 2026-09-23 through the events keyset by each
league's own tag: events and markets open now, and closed since
2026-01-01 ("+" where the count stopped at 4,000 events).

| Candidate | Open events | Open markets | Closed events (2026) | Closed markets | Results source | Work |
| :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| LaLiga | 26 | 554 | 1,535 | 14,580 | openfootball `es.1` | adapter, pack |
| Serie A | 18 | 532 | 1,266 | 11,195 | openfootball `it.1` | adapter, pack |
| Ligue 1 | 15 | 414 | 1,124 | 10,884 | openfootball `fr.1` | adapter, pack |
| Bundesliga | 13 | 372 | 978 | 9,382 | openfootball `de.1` | adapter, pack |
| Eredivisie | 13 | 283 | 774 | 7,420 | openfootball `nl.1` | adapter, pack |
| Champions League | 19 | 969 | 1,007 | 10,524 | venue only | adapter, pack |
| MLS | 181 | 3,106 | 2,285 | 23,455 | venue only | adapter, pack |
| Brasileirão | 28 | 544 | 1,115 | 11,172 | venue only | adapter, pack |
| League of Legends | 96 | 1,809 | 3,251 | 84,494 | venue only; LPDB with a key | adapter, pack, map parser |
| Dota 2 | 31 | 566 | 2,415 | 71,957 | venue only; LPDB with a key | as LoL |
| Valorant | 58 | 997 | 2,451 | 27,183 | venue only; LPDB with a key | as LoL |
| MLB | 339 | 7,718 | 4,000+ | 76,057+ | none open | new parser forms, licensed feed |
| NBA | 22 | 509 | 1,055 | 44,988 | none open | new parser forms, licensed feed |
| NFL | 599 | 27,532 | 463 | 31,102 | none open | new parser forms, licensed feed |
| NHL | 187 | 1,144 | 858 | 5,910 | none open | new parser forms, licensed feed |
| UFC | 56 | 974 | 532 | 5,287 | none open | new parser forms |
| Premier League (for scale) | 9 | 185 | 1,261 | 11,995 | openfootball `en.1` | built |
| CS2 (for scale) | 485 | 4,335 | 4,000+ | 28,275+ | venue only | built |

**Ranking, proposed.** First the four big European football leagues
(LaLiga, Serie A, Ligue 1, Bundesliga): each is the Premier League's shape
with its own results file in openfootball, so the adapter, the props, the
goals and rating signals, the table and the evidence carry over, and each
has about the Premier League's number of markets. Then the other esports
titles, which have the most settled markets of all and the CS2 shape, but
whose rosters wait on the same Liquipedia key as CS2's. Then the North
American leagues, whose question forms and evidence are new. Politics
stays last, behind the jurisdiction and terms review of flag F10. The
short-horizon crypto price markets are noted and not pursued, for the
plan's reasons (a 0.07 fee, a 50 ms taker delay, and no evidence an LLM
can add), which were not re-measured here.

Opening any of them is the owner's decision, one at a time, since each
adds markets the service tracks and captures.
