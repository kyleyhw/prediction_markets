import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import pandas as pd

from src.collectors.kalshi import KalshiCollector


def plot_kalshi_starladder() -> None:
    """
    Fetch and plot historical odds form Kalshi for the Starladder Major.
    """
    series_ticker: str = "KXSTARLADDERBUDAPESTMAJOR"
    collector = KalshiCollector()

    print(f"Fetching Kalshi markets for series: {series_ticker}...")
    markets = collector.fetch_markets(series_ticker=series_ticker)

    if not markets:
        print("No markets found.")
        return

    print(f"Found {len(markets)} markets.")

    os.makedirs("plots/cs2_starladder_budapest_major", exist_ok=True)

    plt.figure(figsize=(12, 8))

    # Start from 7 days ago or reasonable start
    start_dt = datetime.now() - timedelta(days=7)
    start_ts: int = int(start_dt.timestamp())

    plotted_count: int = 0
    for m in markets:
        # Title format: "Will Team X win the..."
        title: str = m.event_name
        team_name: str = (
            title.replace("Will ", "")
            .replace(" win the StarLadder Budapest Major 2025?", "")
            .strip()
        )

        print(f"Processing: {team_name} ({m.event_id})")

        candles: List[Dict[str, Any]] = collector.fetch_candlesticks(
            series_ticker, m.event_id, start_ts=start_ts
        )

        if not candles:
            print(f"  No history for {team_name}")
            continue

        print(f"  Sample candle: {candles[0]}")

        # Candles: {'price': ..., 'volume': ..., 'end_period_ts': ...}
        # Kalshi price is 1-99 cents. Convert to 0.01-0.99

        df = pd.DataFrame(candles)
        if "end_period_ts" not in df.columns:
            continue

        df["timestamp"] = pd.to_datetime(df["end_period_ts"], unit="s")

        # Extract price
        # Prefer 'price.close' (last trade), fallback to mid of yes_ask/yes_bid
        def get_price(row: pd.Series) -> float:
            p = row.get("price", {})
            if isinstance(p, dict) and p.get("close") is not None:
                return float(p["close"]) / 100.0

            # Fallback to mid
            yes_ask_dict = row.get("yes_ask", {})
            yes_bid_dict = row.get("yes_bid", {})

            ask = yes_ask_dict.get("close") if isinstance(yes_ask_dict, dict) else None
            bid = yes_bid_dict.get("close") if isinstance(yes_bid_dict, dict) else None

            if ask is not None and bid is not None:
                return (float(ask) + float(bid)) / 200.0
            elif ask is not None:
                return float(ask) / 100.0
            elif bid is not None:
                return float(bid) / 100.0
            return 0.0

        df["price"] = df.apply(get_price, axis=1)

        current_price: float = df["price"].iloc[-1]

        if current_price < 0.01:  # Skip < 1% chance
            continue

        # Get total volume from market metadata or sum candles?
        # Market metadata has 'volume'
        volume: float = m.volume

        plt.plot(
            df["timestamp"],
            df["price"],
            label=f"{team_name} ({current_price:.2f}) - Vol: ${int(volume):,}",
        )
        plotted_count += 1

    if plotted_count == 0:
        print("No significant data to plot.")
        return

    plt.title("Kalshi Odds History: StarLadder Budapest Major 2025")
    plt.xlabel("Date")
    plt.ylabel("Implied Probability")
    plt.ylim(0, 1)
    plt.grid(True, alpha=0.3)
    plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()

    filename: str = "plots/cs2_starladder_budapest_major/kalshi_winner_odds.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")


if __name__ == "__main__":
    plot_kalshi_starladder()
