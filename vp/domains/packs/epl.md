---
domain: epl
title: Premier League
summary: English football's top division; match results, the title race and many props per match.
updated: 2026-09-23
sources: Polymarket Gamma events under tags 306 and 82 (question forms, types, resolution text); the resolved set built by `vp build-dataset --domain epl` (base rates).
---

## Questions

A match is an event titled `A vs. B` (home side first, club suffixes such
as `FC` kept) with three Yes/No markets: `Will Arsenal FC win on
2026-09-19?` twice (one per side) and `Will A vs. B end in a draw?`.
Before 2026 the forms were `Will PSG win against Barcelona?`, `Will
Liverpool beat Tottenham?` and `Will the match between A and B end in a
draw?`. The title race is `Will Arsenal win the 2026-27 English Premier
League (EPL) Championship?`. Runner-up, top four, relegation, top scorer,
most assists, clean sheets and manager questions are members of the domain
without parsed fields.

Props sit in sibling events (`A vs. B - More Markets`, `- Exact Score`,
`- Player Props`, `- Total Corners`, `- Halftime Result`): totals `A vs.
B: O/U 2.5`, spreads `Spread: A (-1.5)`, exact scores `Exact Score: A 2 - 1
B?`, `Benjamin Sesko: Anytime Goalscorer`, halftime, second-half and
first-to-score results, both teams to score, corners.

## Fields

- `match`: `team_a`, `team_b` (home first), `side` (a team or `draw`),
  `date` (2026 form only).
- `season_winner`: `team`, `season` (empty before 2026).
- Props: see `vp/domains/props.py`; `period` is `full`, `1st_half` or
  `2nd_half`, `stat` is `goals` or `corners`, `line` is the number in the
  question, `team` the team named, `score` like `2-1` or `other`.

## Evidence and the cutoff

`team_results` and `head_to_head` read the venue's own resolved match
markets, settled before the cutoff, with names folded (`Arsenal FC` and
`Arsenal` are one team). Coverage is the venue's listings: a team's
results exist only where Polymarket listed the match, about 2023-08
onward. No lineups, injuries, goals or xG are in the evidence yet (Phase
17); a strategy that needs them cannot be backtested honestly today.

## Base rates

Share of resolved markets whose first outcome won, over the resolved set
from 2023-08-28 to 2026-09-12 (12,716 markets). Markets of one event are
complementary (a match's side, side and draw markets sum to one), so a
rate is a naive prior for one market, not a strategy.

| Kind | Markets | First outcome won |
| :--- | ---: | ---: |
| match, a side wins | 1,655 | 36.6% |
| match, draw | 827 | 26.6% |
| exact score | 2,339 | 5.8% |
| anytime goalscorer | 1,526 | 12.1% |
| total goals, over | 1,282 | 45.7% |
| spread, the favourite covers | 807 | 14.9% |
| both teams to score | 333 | 56.8% |
| total corners, over | 649 | 43.3% |
| season winner | 30 | 10.0% |

## Pitfalls

- Closed is not resolved: a market stops trading at kick-off and resolves
  hours later; only a settled result is a label.
- The first outcome is the event forecast: `Over`, `Yes`, or the first
  team named in a spread.
- Tag 306 was once applied to European cup matches of English clubs, and
  the keyword `epl` names a Dota 2 league and a cricket league; the domain
  excludes them, but a strategy's words should not assume the league.
- Exact scores and goalscorers are long shots with wide spreads; the fee
  is largest at 50/50 and small there, but the spread is not.
- Many spreads and totals at one line (`O/U 0.5`) are near-certain and
  priced so; the edge a strategy sees there is usually the spread.
