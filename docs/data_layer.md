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
| `fee_rate`, `fee_exponent` | The market's own taker fee from its `feeSchedule`; `None` when the venue did not say (`docs/sizing.md`). |
| `market_type`, `description` | The venue's `sportsMarketType` and resolution rules (Phase 15). |
| `resolution_source` | The URL the rules name (the market's, else its event's); a weather market's station is read from it (Phase 17). |
| `neg_risk`, `neg_risk_market_id` | Whether the event's outcomes are exclusive and share one collateral pool, and that pool's id (Phase 17). |

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
docstrings, with the exact question strings the patterns were built from,
all verified against the venue on 2026-09-13 (the counts are from the full
resolved sets built that day, see the
[Phase 7 report](../tests/reports/phase7_data_layer.md)):

- **cs2**: match winners, whose question is the event title
  (`Counter-Strike: Rare Atom vs DEPO (BO3) - Asia Championships Closed
  Qualifier Playoffs`, with the stage before a colon in 2024 titles), per-map
  winners (`... - Map 1 Winner`, read as a match with a `map` field), and
  tournament winners (`Will M80 win ESL Challenger Atlanta 2024?`). The
  props under a match event (`Games Total: O/U 2.5`, map handicaps, odd/even
  kills) are members without fields; they are 70% of the resolved set.
- **weather**: daily temperature buckets at a named city, in four forms
  (`between 54-55°F`, `53°F or below`, `62°F or higher`, and the one-degree
  `17°C`), which are 98% of the resolved set and parse in all but 23
  malformed cases; record ranks and global anomaly buckets. Tornado, rain,
  earthquake and drought questions are members without fields.
- **epl**: season winners (`Will Arsenal win the 2026-27 English Premier
  League (EPL) Championship?`, and the 2024 form without a season) and match
  sides under an `A vs. B` event (`Will Arsenal FC win on 2026-09-19?`,
  `Will A vs. B end in a draw?`, plus the 2024 `win against` and `beat`
  forms). Over/under, exact score, anytime scorer and spread markets are
  members without fields; they are 80% of the resolved set.

The parser returns `None` on anything it does not recognise, and an unparsed
market is still a member of its domain. A parser reads the question only,
never the event title alone, so a prop under a match event is not mistaken
for the match.

## Discovery

`PolymarketSource.discover` combines two routes and de-duplicates by market id.
Paging the catalogue by tag id is exhaustive for that tag; keyword search per
domain keyword catches untagged markets but is relevance-ranked and capped by
the venue. The tag ids, measured on 2026-09-13 from the `tags` field of
discovered events:

| Domain | Listed by | Also seen (not listed by) |
| :--- | :--- | :--- |
| cs2 | 100677 CS2, 100780 counter strike 2, 100602 counter-strike | 64 Esports (all games), 104507 "Counter stike 2", 100635 csgo |
| weather | 84 Weather | 103040 Daily Temperature, 104596 Highest temperature, 832 Global Temp, 87 climate |
| epl | 306 EPL, 82 Premier League | 100350 Soccer, 100639 Games |

Tag 306 was applied in 2024 to Champions League and Europa League ties
involving English clubs, and tag 82 carries "qualify for the Champions
League" markets, so the EPL domain excludes those competitions and the
domestic cups by name. The Esports label is not used for membership because
it is shared with every other game.

The catalogue endpoint caps `limit` at 100 and rejects an `offset` above
2000 with HTTP 422, which the weather tag's closed events exceed. Since
Phase 13 `iter_events` walks `/events/keyset` instead, passing each page's
`next_cursor` back as `after_cursor` (`cursor` and `next_cursor` are
ignored: measured 2026-09-23), which reaches the end of any tag in one pass.

## The Venue's 2026 Interfaces (task 78)

Every endpoint in the client's table (`vp/venues/polymarket.py`) was read
again against the live services on 2026-09-23. Unchanged: search, events
by id (404 on a miss), by slug (exact), by tag; markets by id; the CLOB
book, market (`tokens[].winner`) and price history. New or changed:

- `GET /markets` now lists open markets unless `closed=true` is given;
  `GET /events` has no such default. The client always states `closed`.
- Market objects carry `negRisk`, `negRiskMarketID`, `comboStatus`
  (combinatorial markets; `disabled` on every market sampled), `feesEnabled`
  and `feeSchedule`; the resolution source is on the event. The record keeps
  the negative-risk pair and the source.
- Data API v2 price history needs a time component and serves the whole
  life with `interval=max`; without `bucketSeconds` its bars are twelve
  hours. The client's fallback sent no time component and was refused
  (HTTP 400); it now sends `interval=max`, and the CLOB series, hourly for
  a whole life in one request, stays the first choice.
- Data API v2 resolutions carry no `payouts`: the oracle's answer is
  `price` in 18-decimal fixed point, 1 for the first outcome and 0 for the
  second (of eight settled markets checked, seven agree with the CLOB
  `winner` flags and the eighth has no CLOB flag). The client read no
  winner from any live record; it now reads `price`, and the market-data
  service asks again about records it stored without an answer.
- Data API v2 trades (`{"data", "pagination"}`, snake case) and holders
  (filtered by `condition`) exist for the microstructure signals; nothing
  reads them yet.

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
  served at 60-minute bars: N
  served at 1440-minute bars: N
```

Running with `--max-markets 20` is the quick check; `--no-history` runs the
discovery alone, which takes about two minutes for the largest domain.
`--histories N` fetches histories for N markets only: the most recently
settled of the kinds a backtest scores by default, then props, skipping any
already stored. A few hundred per domain is what the Research Lab uses
(`docs/lab/`). The first build of the lab's data spent its budget on the
Premier League's most recent markets, which were mostly props, and scored 12
matches; preferring the default kinds gave 132. The
`data/` directory is ignored by git.

Price histories are keyed by CLOB token and requested with `interval=max`.
Measured on 2026-09-13, the venue serves bars finer than daily (down to the
raw trade series at `fidelity=10` or below) only for markets that closed
within roughly the last month, and daily bars for everything older back to
2023. `PolymarketSource.history` therefore asks for hourly bars first and
falls back to daily, and each stored series records the `bar_minutes` it
was served at. For a backtest this means the price at an arbitrary cutoff
is known to the hour only for recent markets and to the day otherwise; the
snapshot collector below is what accumulates finer data going forward.

## Snapshots

`vp snapshot --domain cs2 weather epl --depth 5` discovers open markets,
attaches five book levels per side to each outcome, and writes
`data/snapshots/<domain>/<UTC stamp>.parquet`. A listed token whose book the
CLOB answers with 404 (seen once, on a market not yet trading) keeps its
quote without a book. Runs are append-only, so the
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
`market_id, clob_token_id, outcome, timestamp, implied_probability,
bar_minutes`. A file written from an empty list still carries its columns.
