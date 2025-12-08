# Market Search Pipeline Documentation

## Overview
The `find_markets_by_category.py` script provides a unified interface for discovering prediction markets on Polymarket. It supports keyword searching, tag filtering, and exclusion logic to reduce false positives.

## Usage

### Basic Search
Run the script with a category key defined in `market_config.json`:
```bash
uv run python src/analysis/find_markets_by_category.py [category]
```

**Example:**
```bash
uv run python src/analysis/find_markets_by_category.py cs2
uv run python src/analysis/find_markets_by_category.py temperature
```

### Generating Reports
Use the `--report` flag to save the results to a Markdown file in the `reports/` directory.
```bash
uv run python src/analysis/find_markets_by_category.py weather --report
```
*Output:* `reports/market_report_weather_YYYYMMDD_HHMMSS.md`

### Fetching Orderbooks
Use the `--book` flag to fetch full orderbook depth (slower, but useful for liquidity analysis).
```bash
uv run python src/analysis/find_markets_by_category.py cs2 --book
```

## Batching and Ordering
Refers to how the script retrieves data from the Polymarket API:
- **Pagination**: The script uses **offset-based pagination** (e.g., fetching 100 markets at a time).
- **Ordering**: The fetch order depends on the API's default behavior and is **not guaranteed** to be sorted by volume or liquidity during the request.
- **Sorting**: The script sorts the results **client-side** (in memory) by Volume (descending) *after* all matches are found.

## Configuration
The search logic is driven by `src/analysis/market_config.json`.

### Structure
```json
{
    "category_name": {
        "keywords": ["List", "of", "substrings"],
        "tags": ["Exact", "Metadata", "Matches"],
        "exclude": ["Terms", "to", "exclude"]
    }
}
```

### Logic
A market is included if:
1. It does **NOT** contain any term from the `exclude` list in its title.
2. **AND** (It contains a `keyword` substring **OR** matches a `tag`).

### Categories
- **cs2**: Counter-Strike 2 esports.
- **weather**: General weather markets.
- **temperature**: Specific daily temperature markets (e.g., "Highest temperature in Seattle").
