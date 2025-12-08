# Prediction Market Efficiency Analysis Framework

## Overview
This project provides a **generalized framework** for investigating the efficiency of prediction markets across multiple platforms (Polymarket and Kalshi). While initially instantiated for **Counter-Strike 2 (CS2)** and **English Premier League (EPL)**, the core architecture is designed to be agnostic to the specific sport or event category.

The primary objective is to provide a robust pipeline to:
1.  **Fetch** real-time market data from disparate APIs.
2.  **Standardize** data into a common schema.
3.  **Analyze** cross-platform efficiency, spreads, and arbitrage opportunities.

This generality enables researchers and traders to easily extend the work to new domains (e.g., Elections, NBA, NFL) simply by updating the configuration, without rewriting the core collection or analysis logic.

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
│   ├── math_and_logic.md     # Mathematical principles and formulas
│   └── metrics_and_plots.md  # Guide to interpreting plots
├── plots/                    # Generated visualizations
├── reports/                  # Generated market search reports
├── src/
│   ├── analysis/             # Analysis logic (Arbitrage, Visualization)
│   ├── collectors/           # Data fetching scripts (Poly, Kalshi)
│   ├── utils/                # Helper functions (Matching)
│   ├── config.py             # Category configuration
│   └── main.py               # Main pipeline entry point
├── tests/                    # Unit and integration tests
├── .gitignore
├── investigate_kalshi.py     # Investigation script
├── PROJECT_PLAN.md           # Implementation roadmap
├── README.md                 # This file
└── requirements.txt          # Python dependencies
```

## Documentation

Detailed documentation is available in the `docs/` directory:

*   **[Documentation Index](docs/index.md)**: The main entry point for all documentation.
*   **[Definitions & Glossary](docs/definitions.md)**: **(New)** Comprehensive guide to terminology, schema fields, and metric calculations.
*   **[Mathematical Principles](docs/math_and_logic.md)**: Explains odds calculation, arbitrage formulas, and matching logic.
*   **[System Architecture](docs/architecture.md)**: Details the design patterns and ETL pipeline structure.
*   **[Metrics and Plots](docs/metrics_and_plots.md)**: Guide to interpreting plots.
*   **[API Data Models](docs/api_specs/data_models.md)**: Details the `MarketEvent` schema and cross-platform normalization.
*   **[Current State](CURRENT_STATE.md)**: Summary of current capabilities and limitations.

## Getting Started

### Prerequisites
*   Python 3.12+
*   `uv` (Universal Python Package Manager)

### Installation
1.  Clone the repository.
2.  Install `uv` (if not already installed):
    ```bash
    pip install uv
    ```
3.  Sync dependencies and install the project:
    ```bash
    uv sync
    ```
4.  Install pre-commit hooks:
    ```bash
    uv run pre-commit install
    uv run pre-commit run --all-files
    ```

### Usage
The project exposes a Command Line Interface (CLI) tool named `pm` (Prediction Markets).

**Run commands using `uv run`:**

*   **Visualize Bid/Ask Spread (Candles)**:
    ```bash
    uv run pm spread
    ```
    Generates a plot showing the bid-ask range for each team on both platforms, highlighting arbitrage opportunities.

*   **Compare Odds**:
    ```bash
    uv run pm compare
    ```
    Generates a bar chart comparing the implied probabilities and volume for Starladder Major.

*   **Analyze Arbitrage History**:
    ```bash
    uv run pm arbitrage
    ```
    Plots the historical arbitrage spread over time.

*   **Analyze Market Slippage**:
    ```bash
    uv run pm slippage
    ```
    Analyzes the cost of entry and slippage for various bet sizes ($100 - $10k) based on current market depth.

*   **Plot Individual Platform Odds**:
    ```bash
    uv run pm plot-poly   # Polymarket
    uv run pm plot-kalshi # Kalshi
    ```

*   **View Help**:
    ```bash
    uv run pm --help
    ```

### Development Workflow

This project adheres to strict code quality standards enforced by `ruff` and `ty`.

*   **Linting & Formatting**:
    ```bash
    uv run ruff check .      # Lint
    uv run ruff format .     # Format
    ```

*   **Type Checking**:
    ```bash
    uv run ty check          # Static Type Analysis
    ```

*   **Pre-commit Hooks**:
    Commits are automatically checked. To run manually:
    ```bash
    uv run pre-commit run --all-files
    ```



## Methodological Approach
The project employs a modular **Extract-Transform-Load (ETL)** architecture designed for extensibility:

1.  **Generalized Data Collection**: We utilize a `BaseCollector` pattern to interface with the Polymarket Gamma API and Kalshi V2 API. This abstraction allows for the easy addition of new platforms.
2.  **Configuration-Driven Execution**: The `src/config.py` file serves as the central control plane. Adding support for a new category (e.g., "US Elections") is as simple as defining its Platform Tags and Series Tickers in this configuration.
3.  **Standardization**: All market data is normalized into a uniform `MarketEvent` structure, decoupling the analysis layer from API-specific quirks.
4.  **Cross-Platform Matching**: Fuzzy string matching algorithms align events across platforms, enabling direct comparison of odds regardless of naming conventions.
5.  **Analysis**: We compute spreads and identify arbitrage conditions ($P_{ask, A} < P_{bid, B}$) on the standardized dataset.

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
