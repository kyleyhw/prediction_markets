# Data Models and Standardization

## Overview
This document details the standardized data models used across the Prediction Markets framework. The core of this system is the `MarketEvent` class, which serves as a unified schema for disparate data sources (Polymarket, Kalshi).

## MarketEvent Schema
Defined in `src/collectors/base.py`.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `str` | Unique identifier (Ticker or Token ID). |
| `event_name` | `str` | The question or title of the market. |
| `platform` | `str` | Source platform (`polymarket` or `kalshi`). |
| `best_bid` | `float` | **Standardized**: Highest price a buyer is willing to pay. |
| `best_ask` | `float` | **Standardized**: Lowest price a seller is willing to accept. |
| `mid_price` | `float` | **Standardized**: `(best_bid + best_ask) / 2`. |
| `spread` | `float` | **Standardized**: `best_ask - best_bid`. |
| `last_price` | `float` | **Standardized**: Price of the last trade. |
| `orderbook` | `dict` | **Standardized**: Full depth. `{'bids': [{'price': float, 'size': float}], 'asks': [...]}`. |
| `volume` | `float` | Total volume traded (USD). |
| `liquidity` | `float` | Total liquidity in the market (USD). |

## Standardization Logic

### Polymarket
*   **Source**: Gamma API & CLOB API.
*   **Best Bid/Ask**: Derived directly from the CLOB orderbook (Top of Book).
*   **Orderbook**: Full depth fetched via `fetch_orderbook(token_id)`.
*   **Last Price**: Derived from `outcomePrices` (Gamma API).

### Kalshi
*   **Source**: V2 API (`/markets`).
*   **Best Bid/Ask**: Derived from `yes_bid` / `yes_ask` (converted from cents to 0.0-1.0).
*   **Orderbook**: Simulated from Top of Book (API summary does not provide full depth).
    *   `bids`: `[{'price': yes_bid, 'size': 0.0}]`
    *   `asks`: `[{'price': yes_ask, 'size': 0.0}]`
*   **Last Price**: Derived from `price` field.

## Usage
All analysis scripts (e.g., `pm compare`, `pm slippage`) consume `MarketEvent` objects. This ensures that downstream logic does not need to handle platform-specific quirks.

```python
from src.collectors.polymarket import PolymarketCollector

collector = PolymarketCollector()
events = collector.fetch_markets()

for event in events:
    print(f"{event.platform}: {event.best_bid} / {event.best_ask} (Spread: {event.spread:.2%})")
```
