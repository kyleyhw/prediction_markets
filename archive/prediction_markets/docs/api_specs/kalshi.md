# Kalshi API Specification

## Overview
Kalshi uses a RESTful API (V2) for market data and trading.

## Base URL
`https://api.elections.kalshi.com/trade-api/v2` (Public Market Data)

## Key Endpoints

### 1. Fetch Markets
*   **Endpoint**: `/markets`
*   **Method**: `GET`
*   **Parameters**:
    *   `limit`: Number of markets to return.
    *   `series_ticker`: Filter by series (e.g., `KXCSGOGAME`).
    *   `status`: Filter by status (e.g., `open`, `closed`).
*   **Response**: List of markets with current Bid/Ask prices and volume.

### 2. Historical Data
Kalshi provides historical data for markets.
*   **Endpoint**: `/markets/{ticker}/history` (or similar candlestick endpoints in V2).
*   **Method**: `GET`
*   **Availability**: Yes. The API allows retrieval of historical price history (candlesticks), trade history, and order book snapshots for both active and closed markets. This is essential for backtesting strategies.

## Authentication
Public market data endpoints are generally accessible without an API key, but rate limits are stricter. Authenticated access (via API Key) is recommended for high-frequency polling and required for trading.
