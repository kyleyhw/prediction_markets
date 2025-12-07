# Project Plan: Prediction Market Efficiency Analysis (CS2 & EPL)

## Phase 1: Data Acquisition
1.  [completed] Implement `PolymarketCollector` in `src/collectors/polymarket.py` using Gamma API (GraphQL/REST) to fetch markets by tag.
2.  [completed] Implement `KalshiCollector` in `src/collectors/kalshi.py` using V2 REST API to fetch markets by series ticker.
3.  [completed] Define standardized `MarketEvent` data model in `src/collectors/base.py` and implement JSON/CSV storage logic.

## Phase 2: Analysis & Visualization
1.  [completed] Implement fuzzy event matching utility in `src/utils/matching.py` using `difflib` to align events across platforms.
2.  [completed] Develop arbitrage analysis script in `src/analysis/arbitrage.py` to calculate spreads and identify risk-free opportunities.
3.  [completed] Create visualization scripts (`src/analysis/visualize.py`) to plot market counts and price discrepancies.

## Phase 3: Generalization & Multi-Sport Support
1.  [completed] Create configuration system in `src/config.py` to map categories (CS2, EPL) to platform-specific identifiers.
2.  [completed] Refactor `main.py` and collectors to iterate through configured categories and handle dynamic tagging.
3.  [pending] Finalize English Premier League (EPL) support by discovering the correct Kalshi series ticker and verifying event overlap.

## Phase 4: Historical Analysis (Current Focus)
1.  [completed] Verification of historical data access for closed markets (Polymarket Gamma/CLOB).
    *   Result: Closed/Settled markets (e.g., 2024 Election) return 400/404 errors via API, confirming archival/cold storage.
2.  [completed] CS2 Starladder Analysis.
    *   Fetches live/active history for Polymarket and Kalshi.
    *   Generates Arbitrage and Candlestick plots.
3.  [shelved] Authenticated Data Fetching for Kalshi.
    *   Pending user need for specific closed market data that requires auth.

## Phase 5: Documentation
1.  [completed] Document mathematical principles (odds derivation, arbitrage formulas) in `docs/math_and_logic.md`.
2.  [completed] Document system architecture (ETL pipeline, design patterns) in `docs/architecture.md`.
3.  [completed] Update `README.md` with ASCII directory tree, installation instructions, and documentation links.

## Future Extensions
1.  [pending] Build automated trading bot to execute arbitrage trades when opportunities exceed a defined threshold.
2.  [pending] Implement historical backtesting framework to analyze market efficiency improvements over time.
3.  [pending] Create web dashboard (Streamlit/Dash) to visualize live arbitrage opportunities and market spreads.
