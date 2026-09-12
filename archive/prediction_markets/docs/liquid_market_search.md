# Liquid Market Search Documentation

## Overview
The `find_liquid_markets.py` script is designed to identify **active and tradable** markets based on financial metrics rather than specific topics. It is useful for finding arbitrage opportunities, high-volume events, or liquid markets suitable for larger positions.

## Functionality
Unlike `find_markets_by_category.py` which filters by keyword/tag, this script filters by:
- **24h Volume**: Recent trading activity.
- **Liquidity**: Depth of the orderbook.
- **Spread**: Tightness of the bid-ask spread.

## Usage

### Basic Usage
Find the top 100 markets with default filters (Vol > $1k, Liq > $500, Spread < 10%):
```bash
uv run python src/analysis/find_liquid_markets.py
```

### Advanced Filtering
Find highly liquid markets with very tight spreads:
```bash
uv run python src/analysis/find_liquid_markets.py --min-vol 10000 --min-liq 5000 --max-spread 0.02
```

### Filtering by Tag
You can restrict the search to a broad category (e.g., "Sports") while still applying financial filters:
```bash
uv run python src/analysis/find_liquid_markets.py --tag "Sports" --min-vol 5000
```
*Note: `--tag` checks for substring matches in the market's tags.*

## Batching and Ordering
- **Pagination**: The script fetches markets in batches (default: 100) using API offsets.
- **Ordering**: The strict fetch order is determined by the API defaults.
- **Sorting**: Final results are sorted **client-side** by 24h Volume (descending) before display/reporting. Thus, if you only fetch a limited number (e.g., `--limit 100`), you might miss high-volume markets that appear later in the API's pagination order unless you use `--all`.

### Server-Side Filtering
Use `--slug` to filter by Polymarket's internal tag slug (more efficient than `--tag` for large datasets):
```bash
uv run python src/analysis/find_liquid_markets.py --slug "nba"
```

### Generating Reports
Generate a Markdown report of the findings in `reports/`:
```bash
uv run python src/analysis/find_liquid_markets.py --min-vol 5000 --report
```
*Output:* `reports/liquid_markets_report_YYYYMMDD_HHMM.md`

## Arguments
| Argument | Default | Description |
| :--- | :--- | :--- |
| `--min-vol` | 1000 | Minimum 24-hour volume in USD. |
| `--min-liq` | 500 | Minimum liquidity in USD. |
| `--max-spread` | 0.10 | Maximum bid-ask spread (0.10 = 10%). |
| `--limit` | 100 | Number of markets to fetch (batch size). |
| `--all` | False | Fetch **ALL** active markets (slow, handles pagination). |
| `--report` | False | Save results to a Markdown file. |
