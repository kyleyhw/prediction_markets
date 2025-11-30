# Mathematical Principles and Logic

This document details the mathematical frameworks and logical algorithms employed in the **Prediction Markets Analysis** project. It covers the derivation of probabilities from market prices, the conditions for arbitrage, and the string similarity metrics used for event matching.

## 1. Odds and Probability Derivation

Prediction markets allow participants to trade contracts that pay out a fixed amount (usually $1.00 or $1.00 equivalent) if a specific event occurs. The market price of such a contract can be interpreted as the market's consensus probability of that event occurring.

### 1.1. Polymarket (Cryptocurrency-based)

Polymarket operates on a Central Limit Order Book (CLOB) and historically used an Automated Market Maker (AMM). Prices are quoted in USDC (United States Dollar Coin).

For a binary event with outcomes $\{Yes, No\}$:
Let $P_{Poly}$ be the price of the "Yes" outcome in USDC.
Since the payout is $1.00 USDC if the event occurs, the implied probability $\pi_{Poly}$ is given by:

$$ \pi_{Poly} = \frac{P_{Poly}}{1.00} $$

**Simplification**: We assume $1 USDC \approx 1 USD$. We ignore gas fees and slippage for the theoretical probability calculation, though they are critical for practical arbitrage execution.

### 1.2. Kalshi (Regulated Exchange)

Kalshi is a CFTC-regulated exchange where contracts are priced in cents, with a payout of $1.00 (100 cents).

Let $P_{Kalshi}$ be the price of the "Yes" outcome in cents (an integer $n \in [1, 99]$).
The implied probability $\pi_{Kalshi}$ is:

$$ \pi_{Kalshi} = \frac{P_{Kalshi}}{100} $$

## 2. Arbitrage Analysis

Arbitrage opportunities arise when the implied probabilities for the same event differ significantly across platforms, allowing a trader to buy low on one platform and sell high (or take the opposite side) on another to guarantee a profit.

### 2.1. Price Discrepancy (Spread)

We define the spread $\Delta$ as the absolute difference between the implied probabilities:

$$ \Delta = |\pi_{Poly} - \pi_{Kalshi}| $$

### 2.2. Arbitrage Condition

A theoretical arbitrage opportunity exists if the spread exceeds the sum of all transaction costs (fees, slippage, etc.).

Let $C_{Poly}$ and $C_{Kalshi}$ be the transaction costs (as a percentage of notional value) on Polymarket and Kalshi respectively.
A profitable trade is possible if:

$$ \pi_{Poly} - \pi_{Kalshi} > C_{Poly} + C_{Kalshi} \quad (\text{Buy Kalshi, Sell Poly}) $$
$$ \text{OR} $$
$$ \pi_{Kalshi} - \pi_{Poly} > C_{Poly} + C_{Kalshi} \quad (\text{Buy Poly, Sell Kalshi}) $$

**Note**: Since we cannot easily "short" or "sell" a contract we don't own on these platforms without borrowing (which is not standard), "selling" usually implies buying the *opposite* outcome (No).
If $\pi(Yes) + \pi(No) = 1$, then selling "Yes" at price $P$ is equivalent to buying "No" at price $1-P$.

Thus, the practical arbitrage check involves comparing the "Yes" price on one platform to the "No" price on the other:

$$ P_{Poly}(Yes) + P_{Kalshi}(No) < 1.00 $$

If this sum is less than 1.00, one can buy "Yes" on Polymarket and "No" on Kalshi and guarantee a payout of 1.00 for a cost less than 1.00.

## 3. Event Matching Logic

To compare odds, we must identify identical events across platforms. Since there is no common unique identifier (UID), we employ fuzzy string matching.

### 3.1. Sequence Similarity

We use the `difflib.SequenceMatcher` which implements a variation of the Ratcliff/Obershelp pattern matching algorithm.
The similarity ratio $S$ between two strings $A$ and $B$ is defined as:

$$ S(A, B) = \frac{2 \cdot M}{L_A + L_B} $$

Where:
*   $M$ is the number of matching characters.
*   $L_A$ is the length of string $A$.
*   $L_B$ is the length of string $B$.

### 3.2. Matching Algorithm

1.  **Normalization**: Strings are converted to lowercase, and common stop words (e.g., "Will", "the") are removed to reduce noise.
2.  **Thresholding**: We define a similarity threshold $\tau$ (e.g., 0.6 or 60%).
3.  **Selection**: For each event $E_A$ in set $A$, we find $E_B$ in set $B$ that maximizes $S(E_A, E_B)$.
4.  **Validation**: If $\max(S) > \tau$, we consider $(E_A, E_B)$ a candidate match.

## References

*   <span id="ref-polymarket">[1] Polymarket Engineering. (n.d.). *Polymarket API Documentation*. Retrieved from https://docs.polymarket.com/</span>
*   <span id="ref-kalshi">[2] Kalshi. (n.d.). *Kalshi API Documentation*. Retrieved from https://kalshi.com/docs</span>
*   <span id="ref-ratcliff">[3] Ratcliff, J. W., & Metzener, D. E. (1988). Pattern Matching: The Gestalt Approach. *Dr. Dobb's Journal*.</span>
