# Polymarket API Metadata & Structures

This document outlines the **metadata structure** returned by the Polymarket Gamma API. It provides detailed origins, interpretations, and calculations for the core fields found in `Event` and `Market` objects.

## 1. Event Object
The top-level object returned by `/events`. Represents a grouping of markets (e.g., a specific game or election).

| Key | Type | Interpretation & Origin | Calculation / Source |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **Unique Event Identifier**. <br> *Origin*: Database Primary Key. | Generated upon event creation. Fixed. |
| `title` | `string` | **Display Title**. High-level name of the event group. <br> *Origin*: Curation/Admin input. | Human-entered string. |
| `slug` | `string` | **URL Identifier**. Part of the specific event URL. <br> *Origin*: Derived from title. | `polymarket.com/event/{slug}` |
| `description` | `string` | **Resolution Rules**. The "contract" text explaining how the market resolves. <br> *Origin*: Curation/Admin input. | Critical for determining edge cases (e.g., "Includes overtime?"). |
| `startDate` | `ISO8601` | **Open Date**. When the event started accepting trading. | Server timestamp. |
| `endDate` | `ISO8601` | **Resolution Date**. When the event is expected to close. | Admin estimate. Markets may resolve earlier or later. |
| `volume` | `string` (float) | **Aggregate Volume**. Total USDC volume for *all* markets in this event. | $\sum (Market\_Volume_{i})$ for all $i$ markets in event. |
| `liquidity` | `string` (float) | **Aggregate Liquidity**. Total depth for *all* markets. | $\sum (Market\_Liquidity_{i})$. |
| `markets` | `list[dict]` | **Individual Markets**. The binary contracts belonging to this event. | See **Market Object** below. |

## 2. Market Object
The specific tradeable contract (e.g., "Yes" or "No").

| Key | Type | Interpretation & Origin | Calculation / Notes |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **Unique Market Identifier**. <br> *Origin*: Database PK. | Used for API lookups (e.g., `/markets/{id}`). |
| `question` | `string` | **Specific Contract Question**. <br> *Origin*: Admin input. | Often identical to Event Title for simple Yes/No events. |
| `slug` | `string` | **Market URL Slug**. | Unique path for this specific questions. |
| `outcomes` | `list[str]` | **The Sides**. Usually `["Yes", "No"]`. | Defines the assets you hold. |
| `outcomePrices` | `list[str]` | **Current Price**. The implied probability of each outcome. <br> *Origin*: **CLOB** Mid-price or Last Trade. | Typically: $\frac{BestBid + BestAsk}{2}$ or Last Traded Price. <br> *Note*: Format is stringified float (e.g., "0.65"). |
| `clobTokenIds` | `list[str]` | **Orderbook Identifiers**. The *Asset IDs* used to place orders. <br> *Origin*: Gnosis Safe / Blockchain Token IDs. | **Critical**: These IDs are required to fetch the specific orderbook (`/book?token_id=...`). <br> Order maps to `outcomes` (Index 0 = "Yes", Index 1 = "No"). |
| `volume` | `string` | **Contract Volume**. Total USDC traded on this specific question. | $\sum (Price \times Size)$ of all historical matches. |
| `liquidity` | `string` | **Contract Liquidity**. A measure of slippage resistance. | Sum of resting limit orders within a tightly defined spread (usually $\pm X\%$). |
| `active` | `bool` | **Trading Status**. `true` = Open for trading. | System flag. |
| `closed` | `bool` | **Settlement Status**. `true` = Market has resolved. | `true` implies `active` is `false`. |

## 3. Orderbook (CLOB) Structure
Data fetched via `clobTokenIds`. This is the "Truth" for price.

| Key | Type | Interpretation | Calculation |
| :--- | :--- | :--- | :--- |
| `bids` | `list[dict]` | **Buy Orders**. People wanting to buy "Yes" (or "No"). | `{price: "0.60", size: "100"}` -> "I will buy 100 shares at 60c". |
| `asks` | `list[dict]` | **Sell Orders**. People wanting to sell. | `{price: "0.62", size: "50"}` -> "I will sell 50 shares at 62c". |
| `mid_price` | `float` | **Fair Value**. The midpoint between best buyer and best seller. | $Mid = \frac{Max(Bid) + Min(Ask)}{2}$ |
| `spread` | `float` | **Cost of Trading**. The gap between buy and sell. | $Spread = Min(Ask) - Max(Bid)$ |

---
**Note on Origins**:
- **Gamma API** (`gamma-api.polymarket.com`): The "Frontend" API. Provides metadata, descriptions, and cached prices (`outcomePrices`). Faster but slightly stale.
- **CLOB API** (`clob.polymarket.com`): The "Exchange" API. Provides raw orderbooks (`bids`/`asks`) and trade history. The source of truth for execution.
