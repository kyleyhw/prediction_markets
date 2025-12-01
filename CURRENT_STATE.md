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
*   **Functionality**: Can fetch and plot granular price history for markets that are currently open.
*   **Method**: Uses Polymarket's CLOB API (`/prices-history`).
*   **Evidence**: `plots/history_604871....png` shows a successful time-series plot for the active "Fed rate hike in 2025?" market.

### 4. Identifier Discovery
*   **Utility**: `src/utils/identifier_discovery.py` successfully scans and lists events from both platforms to help find IDs.
*   **Evidence**: Script output lists active events and their IDs correctly.

---

## ❌ What Does Not Work (Limitations)

### 1. Historical Data for *Closed* Markets
*   **Issue**: Neither the Polymarket CLOB API nor the Gamma API returns price history for markets that have already settled (closed).
*   **Tests**:
    *   Tested with 2021 Bitcoin markets: **Empty Response**.
    *   Tested with 2022 MATIC/Tennis markets: **Empty Response**.
    *   Tested with recent (2024) Euro matches: **Empty Response**.
*   **Conclusion**: Public APIs do not currently support archival data retrieval for settled markets.

### 2. Specific Event Discovery (Esports)
*   **Issue**: Targeted searches for specific tournaments ("Starladder Budapest", "Blast Rivals") yielded no results.
*   **Likely Cause**: Events may not be listed, might be under different naming conventions not matching keywords, or are too old/new for the default API windows.

### 3. Kalshi EPL Data
*   **Issue**: Unable to find "English Premier League" or "Soccer" markets on Kalshi using standard keywords.
*   **Likely Cause**: Specific series tickers or tags are required and are not easily discoverable via broad keyword search.

---

## 📂 Key Files & Evidence

| Component | Status | File Path |
| :--- | :--- | :--- |
| **Polymarket Collector** | 🟢 Working | `src/collectors/polymarket.py` |
| **Kalshi Collector** | 🟢 Working | `src/collectors/kalshi.py` |
| **History Plotter** | 🟡 Partial | `src/analysis/plot_history.py` (Active only) |
| **Discovery Tool** | 🟢 Working | `src/utils/identifier_discovery.py` |
| **Dashboard Plot** | 🟢 Verified | `plots/market_dashboard.png` |
| **History Plot** | 🟢 Verified | `plots/history_*.png` |

## Next Recommended Steps
1.  **Focus on Active Markets**: Pivot analysis to currently live events (e.g., NBA, NFL, Elections) where data is fully accessible.
2.  **Arbitrage Analysis**: Implement real-time arbitrage detection between Polymarket and Kalshi for active overlapping events.
