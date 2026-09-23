---
domain: weather
title: Weather
summary: How hot it gets; daily high and low temperature buckets in cities, and global temperature records.
updated: 2026-09-23
sources: Polymarket Gamma events under tag 84 (question forms, resolution text); the resolved set built by `vp build-dataset --domain weather` (base rates).
---

## Questions

A day in a city is an event of mutually exclusive buckets, one of which
resolves Yes: `Will the highest temperature in London be between 54-55°F
on December 7?`, `... be 53°F or below ...`, `... be 62°F or higher ...`,
and the one-degree form `... be 17°C on September 12?`. Lowest-temperature
events use the same forms. Records: `Will 2025 be the hottest year on
record?`; anomalies: `Will global temperature increase by between 1.10ºC
and 1.14ºC in November 2025?`.

## Fields

- `daily_temperature`: `statistic` (`highest` or `lowest`), `city`,
  `date` (as written), `low` and `high` (inclusive, in the question's
  unit; an open end is empty), `unit` (`°C` or `°F`).
- `record_rank`: `period`, `rank`, `or_lower`.
- `global_anomaly`: `bucket`, `period`.

## Evidence and the cutoff

`daily_highs` returns the realised temperature at a city for dates before
the cutoff, known to the bucket that resolved Yes (not to the degree). The
resolution text names the station (often an airport) and the source
(usually Weather Underground's history for it); the forecast of the day
itself (numerical weather prediction) is not in the evidence yet: the
Open-Meteo archive is rate-limited from the development container and its
free tier is for non-commercial use (F9, Phase 17).

## Base rates

Share of resolved markets whose first outcome won, 2023-10-19 to
2026-09-13 (134,077 markets). A day's buckets sum to one, so the 9.5% is
roughly one over the number of buckets:

| Kind | Markets | First outcome won |
| :--- | ---: | ---: |
| daily temperature bucket | 131,262 | 9.5% |
| global anomaly bucket | 135 | 17.0% |
| record rank | 37 | 27.0% |

## Pitfalls

- The bucket is in the question's unit; °F and °C cities differ in bucket
  width (two degrees against one).
- Resolution is by a named station and source, not the city's average:
  read the resolution text.
- The last day's buckets are priced by traders who see the day's
  forecasts; climatology alone scored −0.19 against the market a day out
  (Phase 9 report).
- Keywords such as "Heat", "Hurricanes" and "Rain" name sports teams; the
  domain excludes the known ones.
