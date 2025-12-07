from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def calculate_average_entry(
    orderbook: List[Dict[str, float]], target_size: float
) -> Optional[float]:
    """
    Calculate the average price to buy 'target_size' amount of contracts.

    Args:
         orderbook (List[Dict[str, float]]): List of orders usually [{'price': 0.1, 'size': 10.0}, ...]
         target_size (float): The amount of capital/votes to deploy?
                              Note: Usually this is "size" in shares or "size" in dollars?
                              Polymarket size is usually shares (contract count).
                              Kalshi is also contracts.
                              The function name implies "buy target_size contracts".

    Returns:
        Optional[float]: Average entry price, or None if insufficient liquidity.
    """
    if not orderbook:
        return None

    filled_size: float = 0.0
    total_cost: float = 0.0

    # Sort by price (best price first). For Bids (selling), high to low. For Asks (buying), low to high.
    # We assume usage sends pre-sorted, or we iterate blindly.
    # But usually this helper is called with sorted list.

    for level in orderbook:
        price = float(level["price"])
        size = float(level["size"])

        needed = target_size - filled_size
        take = min(needed, size)

        total_cost += take * price
        filled_size += take

        if filled_size >= target_size:
            break

    if filled_size < target_size:
        return None  # Not enough liquidity

    return total_cost / filled_size


def analyze_slippage() -> None:
    # 1. Fetch Data
    print("Fetching Starladder Data...")

    # Polymarket
    poly = PolymarketCollector()
    p_event_raw: Optional[Dict[str, Any]] = poly.fetch_event_by_slug(
        "starladder-budapest-major-2025-winner"
    )
    if not p_event_raw:
        print("Polymarket event not found.")
        return
    p_market = poly._parse_market(p_event_raw, p_event_raw["markets"][0])

    # Kalshi
    kalshi = KalshiCollector()
    k_markets = kalshi.fetch_markets(series_ticker="KXSTARLADDERBUDAPESTMAJOR")
    if not k_markets:
        print("Kalshi event not found.")
        return
    k_market = k_markets[0]  # Assuming first is the main one or we match properly

    # 2. Define Bet Sizes
    bet_sizes: List[int] = [100, 500, 1000, 5000, 10000]
    results: List[Dict[str, Any]] = []

    # 3. Calculate Slippage for Polymarket (Yes Outcome -> Buy from Asks)
    print("Calculating Polymarket Slippage...")
    p_asks: List[Dict[str, float]] = sorted(
        p_market.orderbook["asks"], key=lambda x: x["price"]
    )  # Low to High
    for size in bet_sizes:
        avg_price = calculate_average_entry(p_asks, size)
        if avg_price:
            slippage = (avg_price - p_market.best_ask) / p_market.best_ask * 100
            results.append(
                {
                    "Platform": "Polymarket",
                    "Bet Size ($)": size,
                    "Avg Entry Price": avg_price,
                    "Slippage (%)": slippage,
                }
            )

    # 4. Calculate Slippage for Kalshi (Yes Outcome -> Buy from Asks)
    # Note: Kalshi API summary usually only gives top of book.
    print("Calculating Kalshi Slippage (Limited Depth)...")
    k_asks: List[Dict[str, float]] = sorted(
        k_market.orderbook["asks"], key=lambda x: x["price"]
    )
    for size in bet_sizes:
        avg_price = calculate_average_entry(k_asks, size)
        if avg_price:
            slippage = (avg_price - k_market.best_ask) / k_market.best_ask * 100
            results.append(
                {
                    "Platform": "Kalshi",
                    "Bet Size ($)": size,
                    "Avg Entry Price": avg_price,
                    "Slippage (%)": slippage,
                }
            )
        else:
            results.append(
                {
                    "Platform": "Kalshi",
                    "Bet Size ($)": size,
                    "Avg Entry Price": None,
                    "Slippage (%)": None,
                }
            )

    # 5. Visualize
    df = pd.DataFrame(results)
    print(df)

    if not df.empty:
        plt.figure(figsize=(10, 6))
        sns.barplot(data=df, x="Bet Size ($)", y="Slippage (%)", hue="Platform")
        plt.title('Market Slippage Analysis: Cost to Buy "Yes"')
        plt.ylabel("Slippage (%) (Price Impact)")
        plt.xlabel("Bet Size ($)")
        plt.grid(True, alpha=0.3)
        plt.savefig("plots/slippage_analysis.png")
        print("Saved plot to plots/slippage_analysis.png")


if __name__ == "__main__":
    analyze_slippage()
