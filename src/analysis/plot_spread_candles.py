import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np

from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def plot_spread_candles() -> None:
    """
    Visualize bid/ask spreads for Starladder Major across Polymarket and Kalshi.
    """
    print("Fetching Polymarket Data...")
    poly_collector = PolymarketCollector()
    poly_slug = "starladder-budapest-major-2025-winner"
    poly_event: Optional[Dict[str, Any]] = poly_collector.fetch_event_by_slug(poly_slug)

    poly_data: Dict[str, Dict[str, Any]] = {}
    if poly_event:
        for m in poly_event.get("markets", []):
            team: str = str(m.get("groupItemTitle", m.get("question")))
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
                book: Dict[str, Any] = poly_collector.fetch_orderbook(token_id)
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                if bids and isinstance(bids, list):
                    best_bid = float(bids[0].get("price", 0))
                if asks and isinstance(asks, list):
                    best_ask = float(asks[0].get("price", 0))

            # If no book, fallback to 0/1 or outcomePrices if needed, but for spread viz we need real book
            if best_ask == 0.0:
                # Fallback to mid if we have a price but no book (unlikely for active)
                try:
                    outcome_prices = m.get("outcomePrices", ["0"])
                    if isinstance(outcome_prices, list) and outcome_prices:
                        p = float(outcome_prices[0])
                        best_bid = p - 0.01
                        best_ask = p + 0.01
                    else:
                        pass
                except:
                    pass

            poly_data[team.lower()] = {"bid": best_bid, "ask": best_ask, "name": team}

    print("Fetching Kalshi Data...")
    kalshi_collector = KalshiCollector()
    kalshi_series = "KXSTARLADDERBUDAPESTMAJOR"
    kalshi_markets = kalshi_collector.fetch_markets(series_ticker=kalshi_series)

    kalshi_data: Dict[str, Dict[str, Any]] = {}
    for m in kalshi_markets:
        title: str = m.event_name
        team: str = (
            title.replace("Will ", "")
            .replace(" win the StarLadder Budapest Major 2025?", "")
            .strip()
        )
        kalshi_data[team.lower()] = {
            "bid": m.bids[0] if m.bids else 0.0,
            "ask": m.asks[0] if m.asks else 0.0,
            "name": team,
        }

    print("Matching teams...")
    common_teams: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    for p_team, p_info in poly_data.items():
        if p_team in kalshi_data:
            common_teams.append((p_team, p_info, kalshi_data[p_team]))
            continue
        for k_team in kalshi_data.keys():
            if p_team in k_team or k_team in p_team:
                common_teams.append((k_team, p_info, kalshi_data[k_team]))
                break

    if not common_teams:
        print("No matching teams found.")
        return

    # Sort by average price (descending) to put favorites first
    common_teams.sort(key=lambda x: (x[1]["bid"] + x[2]["bid"]) / 2, reverse=True)

    # Plotting
    fig, ax = plt.subplots(figsize=(14, 8))

    names: List[str] = [str(item[1]["name"]) for item in common_teams]
    y_pos = np.arange(len(names))
    height: float = 0.35

    for i, (key, p, k) in enumerate(common_teams):
        # Polymarket Bar (Blue)
        # Range from Bid to Ask
        p_bid: float = float(p.get("bid", 0.0))
        p_ask: float = float(p.get("ask", 0))
        k_bid: float = float(k.get("bid", 0.0))
        k_ask: float = float(k.get("ask", 0))

        p_width = p_ask - p_bid
        if p_width <= 0:
            p_width = 0.005  # Min width for visibility

        ax.broken_barh(
            [(p_bid, p_width)],
            (y_pos[i] - height / 2, height),
            facecolor="#2D9CDB",
            alpha=0.7,
            label="Polymarket" if i == 0 else "",
        )

        # Kalshi Bar (Green)
        k_width = k_ask - k_bid
        if k_width <= 0:
            k_width = 0.005

        ax.broken_barh(
            [(k_bid, k_width)],
            (y_pos[i] + height / 2, height),
            facecolor="#00D1C1",
            alpha=0.7,
            label="Kalshi" if i == 0 else "",
        )

        # Check for Arbitrage and Highlight
        # Arb 1: Poly Bid > Kalshi Ask
        if p_bid > k_ask:
            gap = p_bid - k_ask
            # Draw a connector or highlight region
            rect = patches.Rectangle(
                (k_ask, y_pos[i] - height),
                gap,
                height * 2,
                linewidth=1,
                edgecolor="gold",
                facecolor="gold",
                alpha=0.3,
                hatch="///",
            )
            ax.add_patch(rect)
            ax.text(
                k_ask + gap / 2,
                y_pos[i],
                f"ARB\n{gap:.1%}",
                ha="center",
                va="center",
                fontsize=8,
                color="darkgoldenrod",
                fontweight="bold",
            )

        # Arb 2: Kalshi Bid > Poly Ask
        if k_bid > p_ask:
            gap = k_bid - p_ask
            rect = patches.Rectangle(
                (p_ask, y_pos[i] - height),
                gap,
                height * 2,
                linewidth=1,
                edgecolor="gold",
                facecolor="gold",
                alpha=0.3,
                hatch="///",
            )
            ax.add_patch(rect)
            ax.text(
                p_ask + gap / 2,
                y_pos[i],
                f"ARB\n{gap:.1%}",
                ha="center",
                va="center",
                fontsize=8,
                color="darkgoldenrod",
                fontweight="bold",
            )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names)
    ax.set_xlabel("Price (Probability)")
    ax.set_title("Bid-Ask Spread & Arbitrage Opportunities (Polymarket vs Kalshi)")
    ax.grid(True, alpha=0.2, axis="x")

    # Legend
    handles, labels = ax.get_legend_handles_labels()
    # arb_patch = patches.Patch(facecolor='gold', alpha=0.3, hatch='///', label='Arbitrage Gap')
    # handles.append(arb_patch)
    ax.legend(handles=handles, loc="upper right")

    # Timestamp
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
    ts_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plots/cs2_starladder_budapest_major/spread_candles_{ts_filename}.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")


if __name__ == "__main__":
    plot_spread_candles()
