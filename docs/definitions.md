# Definitions and Metrics Glossary

This document serves as a comprehensive reference for the terminology, data schema, and calculated metrics used within the Prediction Markets Analysis framework.

## 1. Core Terminology

### Market Structure
*   **Event**: A specific question or contest being wagered on (e.g., "Will Team A win the match?").
*   **Market**: A specific contract within an event (often synonymous with Event in binary markets, but an Event can contain multiple Markets).
*   **Outcome**: The possible results of a market (e.g., "Yes", "No").
*   **Platform**: The exchange where the market is traded (e.g., Polymarket, Kalshi).

### Order Book Terms
*   **Order Book**: The list of all open buy and sell orders for a specific contract.
*   **Bid**: An offer to **buy** a contract.
*   **Ask**: An offer to **sell** a contract.
*   **Best Bid**: The **highest** price anyone is currently willing to pay.
*   **Best Ask**: The **lowest** price anyone is currently willing to sell for.
*   **Depth**: The volume of orders available at specific price levels.
*   **Top of Book**: The Best Bid and Best Ask prices.

## 2. Data Schema (`MarketEvent`)

The `MarketEvent` object standardizes data from all platforms.

| Field | Definition |
| :--- | :--- |
| `best_bid` | The price of the highest buy order at the top of the book. |
| `best_ask` | The price of the lowest sell order at the top of the book. |
| `mid_price` | The arithmetic mean of the Best Bid and Best Ask. Used as a proxy for the "fair" market price. |
| `last_price` | The price at which the most recent trade occurred. |
| `spread` | The difference between the Best Ask and Best Bid. |
| `volume` | The total cumulative value (in USD) of all matched trades since market inception. |
| `liquidity` | A **Projected Depth** score derived from the orderbook. It scales the raw order sum by `1/Spread` to estimate the market's capacity to absorb trades. **It is NOT the raw sum of limit orders.** |

## 3. Calculated Metrics & Formulas

### Implied Probability
The market's estimate of the likelihood of an outcome occurring.
*   **Formula**: $P = Price$ (where Price is between 0.0 and 1.0).
*   **Note**: In prediction markets, a price of 60 cents ($0.60) implies a 60% probability.

### Bid-Ask Spread
A measure of market tightness and transaction cost.
*   **Formula**: $Spread = P_{ask} - P_{bid}$
*   **Interpretation**: A lower spread indicates a more liquid and efficient market. High spread implies uncertainty or low liquidity.

### Arbitrage Spread
The potential profit (or loss) from simultaneously buying on one platform and selling on another.
*   **Condition**: Arbitrage exists if $P_{bid, A} > P_{ask, B}$.
*   **Formula**: $Profit = P_{bid, A} - P_{ask, B}$
    *   *Buy on Platform B at Ask price.*
    *   *Sell on Platform A at Bid price.*
*   **Interpretation**:
    *   **Positive (> 0)**: Risk-free profit opportunity (excluding fees).
    *   **Negative (< 0)**: The cost to cross the spread between markets.

### Slippage
The difference between the expected price of a trade and the price at which the trade is actually executed. This occurs when the order size exceeds the liquidity available at the Best Ask/Bid.
*   **Formula**: $Slippage \% = \frac{AvgEntryPrice - BestAsk}{BestAsk} \times 100$
*   **Average Entry Price**: The weighted average price paid to fill a specific order size (e.g., $1,000) by walking up the order book.
    *   $AvgPrice = \frac{\sum (Price_i \times Size_i)}{TotalSize}$

### Fee-Adjusted Profit
The actual profit realized after accounting for exchange fees.
*   **Formula**: $Profit_{net} = (P_{bid, A} \times (1 - Fee_A)) - (P_{ask, B} \times (1 + Fee_B))$
*   **Typical Fees**:
    *   Polymarket: 0% (currently, for limit orders) or small taker fees depending on structure.
    *   Kalshi: Variable transaction fees.

## 4. Platform Specifics

### Polymarket
*   **Price Format**: Decimal (0.0 to 1.0).
*   **Mechanism**: Central Limit Order Book (CLOB) + AMM (Legacy).
*   **Data Source**: Gamma API (Metadata) + CLOB API (Orderbook).

### Kalshi
*   **Price Format**: Cents (1 to 99). Converted to 0.01 - 0.99 for standardization.
*   **Mechanism**: Central Limit Order Book (DCM).
*   **Data Source**: V2 API.
