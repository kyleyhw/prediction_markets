# System Architecture and Design

This document outlines the architectural decisions, component interactions, and design patterns used in the **Prediction Markets Analysis** system.

## 1. High-Level Overview

The system is designed as a modular Extract-Transform-Load (ETL) pipeline specialized for prediction market data. It prioritizes extensibility (adding new markets/platforms) and auditability (saving raw data).

```mermaid
graph LR
    A[Configuration] --> B[Collectors];
    B --> C[Raw Data Storage];
    C --> D[Standardization];
    D --> E[Processed Data Storage];
    E --> F[Analysis Engine];
    F --> G[Visualization & Reporting];
```

## 2. Component Design

### 2.1. Collectors (`src/collectors/`)

*   **Design Pattern**: Strategy Pattern / Template Method.
*   **Base Class**: `BaseCollector` (Abstract Base Class).
    *   Defines the contract (`fetch_markets`) that all collectors must implement.
    *   Enforces the return type `List[MarketEvent]` to ensure downstream consistency.
*   **Implementations**:
    *   `PolymarketCollector`: Handles GraphQL/REST interactions with Polymarket's Gamma API.
    *   `KalshiCollector`: Handles REST interactions with Kalshi's V2 API.
*   **Rationale**: Isolating API-specific logic allows us to update one collector (e.g., if an API changes) without affecting the rest of the system.

### 2.2. Configuration (`src/config.py`)

*   **Structure**: Dictionary-based configuration mapping categories (e.g., "CS2", "EPL") to platform-specific identifiers (Tag IDs, Series Tickers).
*   **Rationale**: Centralizing configuration avoids hardcoding magic strings in the logic. It allows for easy "no-code" addition of new sports or categories by simply updating the config file.

### 2.3. Data Standardization (`src/collectors/base.py`)

*   **Model**: `MarketEvent` (Python Dataclass).
*   **Fields**: `event_id`, `title`, `description`, `outcomes`, `platform`, `url`, `timestamp`.
*   **Rationale**: Different APIs return data in vastly different shapes. Converting them to a single `MarketEvent` model immediately after fetching ensures that the analysis layer is agnostic to the data source.

### 2.4. Analysis Engine (`src/analysis/`)

*   **Arbitrage Logic** (`arbitrage.py`):
    *   Loads processed CSV data.
    *   Uses `src/utils/matching.py` to align events across platforms.
    *   Calculates spreads and flags discrepancies.
*   **Rationale**: Separating analysis from collection allows us to run analysis on historical data without needing to re-fetch from APIs.

## 3. Data Storage Strategy

*   **Raw Data** (`data/raw/`): JSON files.
    *   **Why**: We save the exact response from the API. This is crucial for debugging and for "replaying" the standardization logic if we decide to extract more fields later.
*   **Processed Data** (`data/processed/`): CSV/Parquet.
    *   **Why**: Tabular formats are optimized for the analysis libraries used (Pandas).

## 4. Future Scalability

The current architecture supports horizontal scaling:
*   **New Platforms**: Add a new class in `src/collectors/` inheriting from `BaseCollector`.
*   **New Categories**: Add a new entry in `src/config.py`.
*   **Automation**: The `main.py` script is stateless and can be scheduled via Cron or Airflow.

## References

*   <span id="ref-gang-of-four">[1] Gamma, E., Helm, R., Johnson, R., & Vlissides, J. (1994). *Design Patterns: Elements of Reusable Object-Oriented Software*. Addison-Wesley.</span>
*   <span id="ref-etl">[2] Kimball, R., & Caserta, J. (2004). *The Data Warehouse ETL Toolkit*. Wiley.</span>
