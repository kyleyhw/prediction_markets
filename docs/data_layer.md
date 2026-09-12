# Data Layer

Phase 7 turns the raw Polymarket client into typed market records, decides
which markets belong to each domain, and persists two kinds of data: a
historical dataset of resolved markets for backtesting, and rolling snapshots
of open markets for paper trading. Everything is Polymarket-only.

## The Binary-Contract Record

`vp.markets.schema.BinaryMarket` is a frozen dataclass, one instance per
observation of one market. The fields that matter downstream:

| Field | Meaning |
| :--- | :--- |
| `outcomes` | Exactly two `Outcome`s. The **first** is the event $A$ whose probability is forecast: "Yes" in a Yes/No market, the first-named team in a match market. |
| `p_yes` | Market-implied probability $q$ of the first outcome, from its last price. |
| `resolved_outcome` | The label $y$: `1` if the first outcome won, `0` if the second did, `None` while unresolved, pending or void. |
| `resolution_state` | `unresolved`, `pending` or `resolved`, from the client's evidence ladder. |
| `status`, `trading_closed` | Lifecycle, kept separate from settlement. |
| `best_bid`, `best_ask`, `spread` | Top of book for the first outcome as the venue reports it. |
| `Outcome.bids`, `Outcome.asks` | Book depth per outcome, best price first, when a snapshot was taken with depth. |
| `domain`, `parsed` | Set by the domain adapter: the domain name and the structured fields read from the question. |
| `fetched_at` | UTC time of the observation; a price is meaningless without it. |

A market with a number of outcomes other than two is rejected by
`market_from_record` and skipped by the source. The label is filled only from
settlement evidence; a price pinned at 0.99 on a closed market never sets it.
That rule is inherited from the client and is the single most important
invariant of the dataset, because every scoring statistic in Phase 9 is a
function of $y$.

## Domain Adapters

`vp.domains` holds one `Domain` per forecasting domain. Membership is decided
from signals already present on every market, so discovery costs no extra
requests: the event's venue-assigned tag labels, the event title, and the
question. Exclusion terms are checked first and veto; then a tag-label match or
a keyword match admits. The archived project's experience shaped the lists:
the keyword "Major" matched a military question and "Miami" a hockey one, so
those are exclusions or were dropped.

Each domain also carries a parser that reads a question into structured
fields. Parsing is best-effort and documented per domain in the module
docstrings, with the exact question strings the patterns were built from:

- **cs2**: matches (`Spirit vs Team Falcons (BO3)`) and tournament winners
  (`Will FURIA win the StarLadder Budapest Major 2025?`).
- **weather**: daily temperature buckets at a named city
  (`between 54-55°F`, `53°F or below`, `62°F or higher`), record ranks, and
  global anomaly buckets.
- **epl**: season winners by analogy with the Bundesliga form, and match
  sides under an `A vs B` event.

The EPL match forms are unverified: no EPL question strings were captured by
the archived project. The parser returns `None` on anything it does not
recognise, and an unparsed market is still a member of its domain.

## Discovery

`PolymarketSource.discover` combines two routes and de-duplicates by market id.
Paging the catalogue by tag id is exhaustive for that tag; the only recorded id
is 306 for the Premier League. Keyword search per domain keyword catches
untagged markets but is relevance-ranked and capped by the venue. The tag ids
for CS2 and weather were not recorded and are to be measured on the first live
run; the tag *labels* (`cs2`, `counter strike 2`, `Esports`, `Weather`,
`climate & weather`) are known and are used for membership.

## Resolved Dataset

`vp build-dataset --domain epl` discovers closed markets, keeps those whose
resolution is `resolved` with a named winner, writes them to
`data/markets/<domain>/resolved.parquet`, and fetches each one's full price
history for its first outcome into `data/histories/<domain>/<market_id>.parquet`.
The report it prints is the retrievability measurement the plan asks for:

```
domain: epl
markets seen (closed, in domain): N
resolved with a label: N
resolved but void or split (no label): N
closed but pending (no settlement record): N
still open: N
histories fetched: N (empty: N, errors: N)
```

Running with `--max-markets 20` is the quick check. The `data/` directory is
ignored by git.

## Snapshots

`vp snapshot --domain cs2 weather epl --depth 5` discovers open markets,
attaches five book levels per side to each outcome, and writes
`data/snapshots/<domain>/<UTC stamp>.parquet`. Runs are append-only, so the
directory accumulates a time series of books that later phases use as backtest
input and as the paper-trading feed. With the default request spacing of
0.35 s per host, a market with depth costs about one second, so a snapshot of
a few hundred markets takes minutes; the spacing is set by
`VP_POLYMARKET_MIN_INTERVAL`.

## Parquet Schemas

Both schemas are explicit in `vp.markets.store`. The `markets` table flattens
the two outcomes into `outcome_0_*` and `outcome_1_*` columns, stores each book
as a list of `{price, size}` structs, `tags` as a list of strings and `parsed`
as a string map. The `histories` table has one row per point:
`market_id, clob_token_id, outcome, timestamp, implied_probability`. A file
written from an empty list still carries its columns.
