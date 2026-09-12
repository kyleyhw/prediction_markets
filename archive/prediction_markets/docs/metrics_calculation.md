# Metrics Calculation

## Overview
The `src/analysis/calculate_metrics.py` module provides standardized functions for calculating market efficiency metrics. Currently, it focuses on **Slippage** and **Average Entry Price**.

## Features

### 1. Average Entry Price
Calculates the weighted average price to acquire a specific volume of contracts from an orderbook.

**Function**: `calculate_average_entry(orderbook, target_size)`

**Logic**:
1. Sorts the orderbook (Asks: Low to High).
2. Iterates through price levels, consuming liquidity until `target_size` is filled.
3. Returns `Total Cost / Target Size`.

**Returns**:
- `float`: Weighted average price.
- `None`: If there is insufficient liquidity to fill the order.

### 2. Slippage
Calculates the percentage difference between the **Average Entry Price** and the **Best Available Price** (Entry Price relative to spot).

**Function**: `calculate_slippage(orderbook, best_price, target_sizes)`

**Formula**:
$$Slippage \% = \left( \frac{\text{Average Entry Price} - \text{Best Price}}{\text{Best Price}} \right) \times 100$$

**Usage**:
```python
from src.analysis.calculate_metrics import calculate_slippage

# Example Orderbook (Asks)
orderbook = [
    {"price": 0.50, "size": 100},
    {"price": 0.51, "size": 200}
]

# Calculate for $100 and $1000 sizes
results = calculate_slippage(orderbook, best_price=0.50, target_sizes=[100, 1000])
```

## Future Metrics
This module is designed to be extended with additional metrics such as:
- Spread calculation
- Arbitrage opportunity detection
- Implied probability conversion
