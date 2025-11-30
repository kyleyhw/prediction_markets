# Prediction Market Efficiency Analysis (CS2 & EPL)

## Overview
This project investigates the nature and efficiency of prediction markets by comparing betting odds for **Counter-Strike 2 (CS2)** and **English Premier League (EPL)** matches on **Polymarket** and **Kalshi**.

The primary objective is to fetch real-time market data, standardize it into a common format, and perform comparative analysis to identify:
*   Price spreads between platforms.
*   Market efficiency and convergence.
*   Potential arbitrage opportunities.

## Directory Structure

```ascii
prediction_markets/
├── data/
│   ├── raw/                  # Raw JSON responses from APIs
│   └── processed/            # Standardized CSV files
├── docs/                     # Project Documentation
│   ├── api_specs/            # API details
│   ├── architecture.md       # System design and rationale
│   ├── index.md              # Documentation table of contents
│   └── math_and_logic.md     # Mathematical principles and formulas
├── src/
│   ├── analysis/             # Analysis logic (Arbitrage, Visualization)
│   ├── collectors/           # Data fetching scripts (Poly, Kalshi)
│   ├── utils/                # Helper functions (Matching)
│   ├── config.py             # Category configuration
│   └── main.py               # Main pipeline entry point
├── tests/                    # Unit and integration tests
├── .gitignore
├── find_identifiers.py       # Utility to discover API tags/tickers
├── investigate_kalshi.py     # Investigation script
├── PROJECT_PLAN.md           # Implementation roadmap
├── README.md                 # This file
└── requirements.txt          # Python dependencies
```

## Documentation

Detailed documentation is available in the `docs/` directory:

*   **[Documentation Index](docs/index.md)**
*   **[Mathematical Principles](docs/math_and_logic.md)**: Explains odds calculation, arbitrage formulas, and matching logic.
*   **[System Architecture](docs/architecture.md)**: Details the design patterns and ETL pipeline structure.

## Getting Started

### Prerequisites
*   Python 3.10+
*   `pip` or `poetry`

### Installation
1.  Clone the repository.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Usage
*   **Fetch Data**:
    ```bash
    python -m src.main
    ```
    This will fetch data for all configured categories (CS2, EPL) and save it to `data/processed/`.

*   **Run Analysis**:
    ```bash
    python -m src.analysis.arbitrage
    ```

## Methodological Approach
1.  **Data Collection**: We utilize the Polymarket Gamma API and Kalshi V2 API to query markets filtered by configured categories (CS2, EPL).
2.  **Standardization**: All market data is normalized into a `MarketEvent` structure containing event names, outcomes, best bid/ask prices, and liquidity metrics.
3.  **Matching**: Fuzzy string matching is employed to align events across platforms (e.g., handling team name variations).
4.  **Analysis**: We compute the spread between the best ask on one platform and the best bid on the other to detect arbitrage conditions ($P_{ask, A} < P_{bid, B}$).

## Odds Calculation Mechanisms

### Polymarket (AMM & Order Book)
Polymarket uses a hybrid system. Historically, it used an **Automated Market Maker (AMM)** (specifically a CPMM - Constant Product Market Maker) where odds were determined by the ratio of tokens in the liquidity pool.
*   **Formula**: $Price(Yes) = \frac{Pool(No)}{Pool(Yes) + Pool(No)}$
*   **Current State**: Polymarket has migrated towards a **CLOB (Central Limit Order Book)** model for many markets. The "price" returned by the API typically represents the **mid-market price** or the **last traded price**, reflecting the probability $P$ where $0 \le P \le 1$.

### Kalshi (Order Book)
Kalshi operates as a traditional designated contract market (DCM) with a **Central Limit Order Book**.
*   **Mechanism**: Users place limit orders (Bid/Ask).
*   **Odds**: The "odds" are simply the price of the contract, ranging from 1 cent to 99 cents. A price of 60 cents implies a 60% probability of the event occurring.
*   **API Data**: The API provides the best Bid and best Ask. We use these to calculate the spread and the mid-market probability.

## References
*   [Polymarket API Documentation](https://docs.polymarket.com/)
*   [Kalshi API Documentation](https://docs.kalshi.com/)
