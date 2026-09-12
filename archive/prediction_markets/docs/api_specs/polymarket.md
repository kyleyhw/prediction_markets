# Polymarket API Specification

## Overview
Polymarket uses the **Gamma API** (GraphQL/REST) for market discovery and the **CLOB API** for order book interaction.

## Base URL
`https://gamma-api.polymarket.com`

## Key Endpoints

### 1. Fetch Markets
*   **Endpoint**: `/events`
*   **Method**: `GET`
*   **Parameters**:
    *   `limit`: Number of events to return.
    *   `tag_id`: Filter by category (e.g., `306` for EPL).
    *   `slug`: Filter by event slug.
*   **Response**: List of events containing market details, outcomes, and current prices.

### 2. Historical Data
Polymarket provides historical price data through specific endpoints.
*   **Endpoint**: `/pricesForMarket` (or via CLOB API)
*   **Parameters**:
    *   `hash`: The market's condition ID or token ID.
    *   `interval`: Time interval (e.g., `1h`, `1d`).
*   **Availability**: Yes, the API supports fetching historical timeseries data for analysis and backtesting.

## Authentication
Public endpoints (like Gamma API) do not require authentication. Trading endpoints require an API key and wallet signature.
