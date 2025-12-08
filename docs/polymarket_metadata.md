# Polymarket API Metadata & Tags

This document outlines the metadata structure returned by the Polymarket Gamma API and provides a detailed guide to interpreting market categories (tags).

## Event Object Structure
The top-level object returned by `/events` contains high-level metadata about a group of markets (e.g. "Will Trump do X?").

| Key | Type | Description |
| :--- | :--- | :--- |
| `id` | string | Unique event ID |
| `title` | string | Display title of the event |
| `slug` | string | URL slug for the event page |
| `description` | string | Detailed resolution criteria and description |
| `startDate` | string (ISO) | Event creation/start date |
| `endDate` | string (ISO) | Expected resolution date |
| `creationDate` | string (ISO) | Date the event was created in the system |
| `image` | string (URL) | URL to event image/thumbnail |
| `volume` | string (float) | Total volume across all markets in this event |
| `volume24hr` | float | Volume in the last 24 hours |
| `liquidity` | string (float) | Total liquidity |
| `tags` | list[dict] | List of category tags (see below) |
| `markets` | list[dict] | List of individual markets within this event |

## Market Object Structure
The `markets` list contained within an event object.

| Key | Type | Description |
| :--- | :--- | :--- |
| `id` | string | Unique market ID |
| `question` | string | Specific question (often same as event title for single-market events) |
| `slug` | string | URL slug for this specific market |
| `outcomes` | list[string] | Resolution outcomes (e.g. `["Yes", "No"]`) |
| `outcomePrices` | list[string] | Current price of each outcome (str representation of float) |
| `clobTokenIds` | list[string] | Token IDs for the Orderbook (CLOB) |
| `active` | boolean | Whether the market is currently active |
| `closed` | boolean | Whether the market has ended/settled |
| `volume` | string | Total volume for this specific market |
| `volume24hr` | float | 24h volume for this market |
| `liquidity` | string | Liquidity metric for this market |
| `acceptingOrders` | boolean | If the market handles new orders |
| `ready` | boolean | If the market is fully deployed and ready |

## Tag Categories & Interpretation

Polymarket organizing events using "Tags". These are not strictly hierarchical but tend to cluster into major domains. Below is a guide to interpreting these tags, their origins, and how their markets typically calculate value.

### 1. Global Politics
Markets related to elections, legislation, and geopolitical events.

| Examples | Interpretation | Origin | Calculation / Settlement |
| :--- | :--- | :--- | :--- |
| `US Politics`, `2024 Election`, `Trump`, `Biden`, `Democrat`, `Republican` | Relates to US federal elections or candidate prospects. | **Curated**: Major election cycles usually have dedicated pages/tags. | **Binary**: Pays $1.00 if the specific candidate wins or event happens. Often high volume, long duration. |
| `Geopolitics`, `Ukraine`, `Israel`, `Middle East`, `China` | International relations, conflict outcomes, or major diplomatic agreements. | **Community/Curated**: Often spun up in response to breaking news. | **Binary**: Settles based on reputable news consensus (e.g. "Did X happen by Y date?"). |
| `Government`, `Congress`, `Senate`, `Bill` | Legislative outcomes (e.g. "Will Bill X pass?"). | **Curated**: Specific to legislative sessions. | **Binary**: Verified by official government records (congress.gov). |

### 2. Economics & Macro
Markets tracking financial indicators and central bank policies.

| Examples | Interpretation | Origin | Calculation / Settlement |
| :--- | :--- | :--- | :--- |
| `Fed Rates`, `Jerome Powell`, `Interest Rates` | Predictions on Federal Reserve actions (hikes, cuts, pauses). | **Curated**: Aligned with FOMC meeting schedules. | **Binary**: Settles based on the target rate range announced by the Fed. |
| `Inflation`, `CPI`, `Recession`, `GDP` | Macroeconomic data releases. | **Curated**: Aligned with BLS/BEA release calendars. | **Range/Binary**: Often "Will CPI be > X%?". Verified against official gov data. |
| `Stocks`, `S&P 500`, `NVIDIA`, `GameStop` | Price targets for specific assets or indices by a certain date. | **Community/Curated**: Often appear around earnings calls. | **Binary**: "Will stock close > $X on Date Y?". Verified via Yahoo Finance/Bloomberg. |

### 3. Crypto & Web3
Markets native to the blockchain ecosystem.

| Examples | Interpretation | Origin | Calculation / Settlement |
| :--- | :--- | :--- | :--- |
| `Bitcoin`, `Ethereum`, `Solana`, `ETF` | Price movements ("Will BTC hit $100k?") or regulatory approvals (ETFs). | **Community (High Activity)**: Very popular sector on Polymarket. | **Binary**: Price data usually verified via Oracle (Chainlink) or major exchange composite (Coinbase/Binance). |
| `NFT`, `Airdrop`, `Blur`, `OpenSea` | Ecosystem events: floor prices, token launches, or hack recoveries. | **Community**: Niche markets for specific communities. | **Binary**: Verified on-chain or via specific platform metrics. |

### 4. Sports
Major sporting events and league outcomes.

| Examples | Interpretation | Origin | Calculation / Settlement |
| :--- | :--- | :--- | :--- |
| `NFL`, `NBA`, `Super Bowl`, `Premier League`, `Soccer` | Game winners, championship futures, or player awards (MVP). | **Curated**: Structured around league seasons. | **Binary**: Classic sports betting rules. Pays $1 if team wins. |
| `F1`, `Tennis`, `UFC`, `Cricket` | Individual match or race outcomes. | **Curated**: Event specific. | **Binary**: Official league results. |

### 5. Pop Culture & Other
Entertainment, viral trends, and miscellaneous events.

| Examples | Interpretation | Origin | Calculation / Settlement |
| :--- | :--- | :--- | :--- |
| `Movies`, `Oscars`, `Grammys`, `Taylor Swift` | Awards shows, box office performance, or celebrity news. | **Community**: Highly seasonal (award season). | **Binary**: Verified by official award announcements or Box Office Mojo. |
| `Science`, `SpaceX`, `AI`, `Climate` | Technological milestones (rocket launches) or climate records (hottest year). | **Community**: Interest based. | **Binary**: Verified by NASA, NOAA, or specific scientific bodies. |

---

*Note: The "Calculation" for almost all Polymarket contracts is a binary option structure. A "Yes" share pays out $1.00 (USDC) if the event occurs, and $0.00 otherwise. The price (e.g. $0.60) reflects the market's implied probability (60%).*
