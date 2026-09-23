---
domain: cs2
title: Counter-Strike 2
summary: Esports; series and map winners, tournament winners, handicaps and round totals.
updated: 2026-09-23
sources: Polymarket Gamma events under tags 100677, 100780 and 100602 (question forms, types, resolution text); the resolved set built by `vp build-dataset --domain cs2` (base rates).
---

## Questions

A series is `Counter-Strike: Spirit vs Team Falcons (BO3)`, often with the
stage after a dash; its maps are `Counter-Strike: A vs B - Map 1 Winner`.
Older forms put the stage first (`ESL Counter-Strike Quarterfinals: G2 vs
Liquid`). Tournament winners: `Will FURIA win the StarLadder Budapest Major
2025?`. Props in the same event: `Map Handicap: PLD (-1.5) vs your end
(+1.5)` (series handicap, in maps; `Map Handicap: MOUZ (-1.5)` before
2026), `Games Total: O/U 2.5` (maps played), `Map 1 Total Rounds:
Over/Under 18.5`, `Map 1 Rounds Handicap: A (-6.5) vs B (+6.5)`, `Map 1:
Odd/Even Total Kills?`.

## Fields

- `match`: `team_a`, `team_b`, `format` (`BO1`, `BO3`, `BO5`), `map` (a
  map-winner market), `stage`.
- `tournament_winner`: `team`, `tournament`.
- Props: `spread` with `stat` `maps` or `rounds`, `total` with `stat`
  `maps` or `rounds`, `odd_even` with `stat` `kills` or `rounds`; `period`
  is `full` or `map_N`.

## Evidence and the cutoff

`team_results` and `head_to_head` read settled series markets before the
cutoff (map winners are left out, so a series counts once). Most CS2
markets are listed a day or two before the match and many price histories
are daily bars: a 24-hour cutoff often has no price at all, which the
backtest reports as fewer scored markets. Rosters, map pools and vetoes are
not in the evidence (Phase 17).

## Base rates

Share of resolved markets whose first outcome won, 2024-09-20 to
2026-09-13 (87,918 markets):

| Kind | Markets | First outcome won |
| :--- | ---: | ---: |
| match (series or map), first-named team | 25,196 | 55.2% |
| series handicap, favourite covers | 9,165 | 37.6% |
| maps played, over | 7,591 | 40.8% |
| rounds on a map, over | 14,616 | 34.7% |
| rounds handicap on a map, favourite covers | 15,187 | 32.8% |
| total kills on a map, odd | 6,520 | 49.9% |
| total rounds on a map, odd | 6,521 | 46.3% |
| tournament winner | 919 | 5.4% |

## Pitfalls

- Outcome names are the venue's short names and can be truncated; the
  parsed names from the question are the ones to use.
- A team plays under changing names (academy sides, `ex-` rosters); names
  are folded only for case and club suffixes.
- The map a strategy trades may not be played: map 3 of a BO3 is voided or
  resolved by the venue's rules when the series ends 2-0; read the market's
  resolution text.
- Dota 2 series share tournament and team names; the domain excludes
  them.
