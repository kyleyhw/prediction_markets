# Current State of the Repository

## Overview
This document summarizes the current capabilities, limitations, and verified evidence of the prediction market analysis tools in this repository.

## ✅ What Works (Verified)

### 1. Active Market Data Collection
*   **Polymarket**: Successfully fetches *active* markets using the Gamma API.
*   **Kalshi**: Successfully fetches *active* markets using the V2 API.
*   **Evidence**: `src/collectors/polymarket.py` and `src/collectors/kalshi.py` are functional.
# Current State of the Repository

## Overview
This document summarizes the current capabilities, limitations, and verified evidence of the prediction market analysis tools in this repository.

## ✅ What Works (Verified)

### 1. Active Market Data Collection
*   **Polymarket**: Successfully fetches *active* markets using the Gamma API.
*   **Kalshi**: Successfully fetches *active* markets using the V2 API.
*   **Evidence**: `src/collectors/polymarket.py` and `src/collectors/kalshi.py` are functional.

### 2. Visualization & Dashboards
*   **Market Dashboard**: Generates a comprehensive dashboard showing market counts, volume distribution, liquidity, and implied spreads.
*   **Evidence**: `plots/market_dashboard.png` (generated successfully).

### 3. Historical Data for *Active* Markets
*   **Polymarket**: Can fetch and plot granular price history for markets that are currently open.
*   **Kalshi**: Successfully fetches historical candlesticks for active markets (requires `start_ts` and `end_ts`).
*   **Evidence**: `plots/cs2_starladder_budapest_major/` contains history plots for both platforms.

### 4. Arbitrage Analysis
*   **Functionality**: Can align historical data from both platforms to visualize price differences (arbitrage opportunities) over time.
*   **Evidence**: `plots/cs2_starladder_budapest_major/arbitrage_history.png`.

### 6. CLI Tool
*   **Functionality**: Centralized entry point (`pm`) for all analysis tools.
*   **Evidence**: `src/cli.py` and `pyproject.toml` configuration.

---

## ❌ What Does Not Work (Limitations)

### 1. Historical Data for *Closed* Markets
*   **Issue**: Public APIs do not currently support archival data retrieval for settled markets without authentication.
*   **Status**: Authentication logic implemented but shelved pending user keys.

### 2. Keyword Search for Niche Events
*   **Issue**: Broad keyword searches (e.g., "CS2", "Starladder") sometimes fail to surface specific markets due to API relevance sorting or naming conventions.
*   **Workaround**: Direct URL or Ticker lookup works reliably.

### 3. Kalshi EPL Data
*   **Issue**: Unable to find "English Premier League" or "Soccer" markets on Kalshi using standard keywords.
*   **Likely Cause**: Specific series tickers or tags are required and are not easily discoverable via broad keyword search.

---

## 📂 Key Files & Evidence

| Component | Status | File Path |
| :--- | :--- | :--- |
| **CLI Entry Point** | 🟢 Working | `src/cli.py` |
| **Polymarket Collector** | 🟢 Working | `src/collectors/polymarket.py` |
| **Kalshi Collector** | 🟢 Working | `src/collectors/kalshi.py` |
| **Spread Visualization** | 🟢 Working | `src/analysis/plot_spread_candles.py` |
| **Comparison Plot** | 🟢 Working | `src/analysis/compare_starladder.py` |
| **Arbitrage Plotter** | 🟢 Working | `src/analysis/plot_arbitrage_history.py` |

## Next Recommended Steps
1.  **Authentication**: User to provide API keys to unlock closed market history.
2.  **Automated Monitoring**: Set up a cron job to run `uv run pm arbitrage` periodically.
