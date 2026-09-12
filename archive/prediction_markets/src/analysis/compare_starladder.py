import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt

from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def compare_starladder_odds() -> None:
    """
    Compare odds between Polymarket and Kalshi for the Starladder Major,
    fetching live data and plotting the arbitrage spread.
    """
    print("Fetching Polymarket Data...")
    poly_collector = PolymarketCollector()
    poly_slug = "starladder-budapest-major-2025-winner"
    poly_event: Optional[Dict[str, Any]] = poly_collector.fetch_event_by_slug(poly_slug)

    poly_data: Dict[str, Dict[str, Any]] = {}
    if poly_event:
        print(f"  Found Polymarket Event: {poly_event.get('title')}")
        for m in poly_event.get("markets", []):
            team: str = str(m.get("groupItemTitle", m.get("question")))

            # Fetch Orderbook for Bid/Ask
            clob_ids_raw = m.get("clobTokenIds", "[]")
            clob_ids: List[str] = (
                json.loads(clob_ids_raw)
                if isinstance(clob_ids_raw, str)
                else clob_ids_raw
            )

            best_bid: float = 0.0
            best_ask: float = 0.0

            if clob_ids:
                token_id: str = str(clob_ids[0])
                # print(f"    Fetching book for {team} ({token_id})...")
                book: Dict[str, Any] = poly_collector.fetch_orderbook(token_id)
                bids = book.get("bids", [])
                asks = book.get("asks", [])

                if bids and isinstance(bids, list):
                    best_bid = float(bids[0].get("price", 0))
                if asks and isinstance(asks, list):
                    best_ask = float(asks[0].get("price", 0))

            # Fallback to last price if book is empty (or treat as 0/1)
            outcome_prices = m.get("outcomePrices", ["0"])
            price: float = (
                float(outcome_prices[0])
                if isinstance(outcome_prices, list) and outcome_prices
                else 0.0
            )
            volume: float = float(m.get("volume", 0))

            poly_data[team.lower()] = {
                "price": price,
                "bid": best_bid,
                "ask": best_ask,
                "volume": volume,
                "name": team,
            }

    print("Fetching Kalshi Data...")
    kalshi_collector = KalshiCollector()
    kalshi_series = "KXSTARLADDERBUDAPESTMAJOR"
    kalshi_markets = kalshi_collector.fetch_markets(series_ticker=kalshi_series)

    kalshi_data: Dict[str, Dict[str, Any]] = {}
    print(f"  Found {len(kalshi_markets)} Kalshi markets.")
    for m in kalshi_markets:
        # Title: "Will Team X win..."
        title: str = m.event_name
        team: str = (
            title.replace("Will ", "")
            .replace(" win the StarLadder Budapest Major 2025?", "")
            .strip()
        )

        kalshi_data[team.lower()] = {
            "price": m.last_price,
            "bid": m.best_bid,
            "ask": m.best_ask,
            "volume": m.volume,
            "name": team,
        }

    print("Matching teams...")
    # Simple fuzzy match or direct match
    matches: List[Tuple[str, str]] = []
    for p_team, p_info in poly_data.items():
        # Try direct match
        if p_team in kalshi_data:
            matches.append((p_team, p_team))
            continue

        # Try partial match
        for k_team in kalshi_data.keys():
            if p_team in k_team or k_team in p_team:
                matches.append((p_team, k_team))
                break

    print(f"Found {len(matches)} matching teams.")

    # Prepare Data for Plotting
    names: List[str] = []
    spreads: List[float] = []
    colors: List[str] = []

    for p_key, k_key in matches:
        p = poly_data[p_key]
        k = kalshi_data[k_key]

        name: str = str(p["name"])
        names.append(name)

        # Calculate Arbitrage Spread
        # Arb 1: Buy Kalshi (Ask), Sell Poly (Bid) -> Profit = P_Bid - K_Ask
        # Arb 2: Buy Poly (Ask), Sell Kalshi (Bid) -> Profit = K_Bid - P_Ask

        p_bid: float = float(p.get("bid", 0.0))
        p_ask: float = float(p.get("ask", 0.0))
        k_bid: float = float(k.get("bid", 0.0))
        k_ask: float = float(k.get("ask", 0.0))

        arb1 = p_bid - k_ask
        arb2 = k_bid - p_ask

        # We want to show the "best" opportunity (or the least negative spread)
        # If arb1 > arb2, it means (P_Bid - K_Ask) is the better deal.

        best_spread = max(arb1, arb2)
        spreads.append(best_spread)

        if best_spread > 0:
            colors.append("blue")  # Arbitrage!
        else:
            colors.append("red")  # Negative spread (cost to cross)

    # Plotting
    plt.figure(figsize=(14, 8))

    # Bar chart of Spreads
    bars = plt.bar(names, spreads, color=colors, alpha=0.7)

    # Add value labels
    for bar in bars:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2.0,
            height,
            f"{height:.1%}",
            ha="center",
            va="bottom" if height > 0 else "top",
            fontsize=9,
        )

    plt.axhline(0, color="black", linewidth=0.8, linestyle="--")
    plt.title("Arbitrage Spread (Best Bid - Best Ask) - Polymarket vs Kalshi")
    plt.xlabel("Team")
    plt.ylabel("Spread (Profit/Loss per share)")
    plt.xticks(rotation=45, ha="right")
    plt.grid(True, alpha=0.3, axis="y")

    # Add legend manually
    from matplotlib.patches import Patch

    legend_elements = [
        Patch(facecolor="blue", label="Arbitrage Opportunity (Positive Spread)"),
        Patch(facecolor="red", label="Negative Spread (No Arb)"),
    ]
    plt.legend(handles=legend_elements, loc="upper right")

    # Add timestamp to plot
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plt.figtext(
        0.99,
        0.01,
        f"Generated at: {current_time}",
        horizontalalignment="right",
        fontsize=8,
        color="gray",
    )

    plt.tight_layout()
    os.makedirs("plots/cs2_starladder_budapest_major", exist_ok=True)

    # Timestamped filename
    ts_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plots/cs2_starladder_budapest_major/starladder_spread_comparison_{ts_filename}.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")


if __name__ == "__main__":
    compare_starladder_odds()
