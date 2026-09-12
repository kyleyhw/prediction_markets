import json
import os
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd

from src.collectors.polymarket import PolymarketCollector


def plot_starladder_odds() -> None:
    """
    Fetch and plot historical odds for the Starladder Major from Polymarket.
    """
    slug: str = "starladder-budapest-major-2025-winner"
    collector = PolymarketCollector()

    print(f"Fetching event: {slug}...")
    event: Optional[Dict[str, Any]] = collector.fetch_event_by_slug(slug)

    if not event:
        print("Event not found.")
        return

    print(f"Found Event: {event.get('title')}")

    markets: List[Dict[str, Any]] = event.get("markets", [])
    print(f"Found {len(markets)} markets (teams/outcomes).")

    os.makedirs("plots/cs2_starladder_budapest_major", exist_ok=True)

    plt.figure(figsize=(12, 8))

    plotted_count: int = 0
    for m in markets:
        team_name: str = str(m.get("groupItemTitle", m.get("question")))
        print(f"Processing: {team_name}")

        # Get CLOB ID
        clob_ids_raw = m.get("clobTokenIds", "[]")
        clob_ids: List[str] = (
            json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
        )

        mid: str = str(clob_ids[0]) if clob_ids else str(m.get("id", ""))

        # Fetch history
        # Use "max" or "1h" depending on how long it's been running.
        history: List[Dict[str, Any]] = collector.fetch_price_history(
            mid, interval="max"
        )

        if not history:
            print(f"  No history for {team_name}")
            continue

        df = pd.DataFrame(history)
        if "t" not in df.columns or "p" not in df.columns:
            continue

        df["timestamp"] = pd.to_datetime(df["t"], unit="s")
        df["price"] = df["p"].astype(float)

        # Filter out very low prob teams to keep chart readable
        current_price: float = df["price"].iloc[-1]
        if current_price < 0.01:  # Skip < 1% chance
            continue

        # Get volume
        volume: float = float(m.get("volume", 0))

        plt.plot(
            df["timestamp"],
            df["price"],
            label=f"{team_name} ({current_price:.2f}) - Vol: ${int(volume):,}",
        )
        plotted_count += 1

    if plotted_count == 0:
        print("No significant data to plot.")
        return

    plt.title(f"Polymarket Odds History: {event.get('title')}")
    plt.xlabel("Date")
    plt.ylabel("Implied Probability")
    plt.ylim(0, 1)
    plt.grid(True, alpha=0.3)
    plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()

    # Remove old file if exists
    old_filename: str = "plots/cs2_starladder_budapest_major/winner_odds.png"
    if os.path.exists(old_filename):
        os.remove(old_filename)

    filename: str = "plots/cs2_starladder_budapest_major/polymarket_winner_odds.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")


if __name__ == "__main__":
    plot_starladder_odds()
