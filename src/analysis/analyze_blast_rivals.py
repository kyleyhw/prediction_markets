from datetime import datetime
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import pandas as pd

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector


def analyze_blast_rivals() -> None:
    print("Initializing Collectors...")
    print("Initializing Collectors...")
    # poly = PolymarketCollector()
    kalshi = KalshiCollector()

    # 1. Define Event Identifiers
    kalshi_ticker_spirit = "KXCSGOGAME-25DEC04TSFAZE-TS"
    kalshi_ticker_faze = "KXCSGOGAME-25DEC04TSFAZE-FAZE"

    # 2. Fetch Data
    data: List[Dict[str, Any]] = []

    # Kalshi Data (Fetch First)
    print("Fetching Kalshi Data...")
    try:
        # Fetch candlesticks (1 hour interval)
        # Start time: 7 days ago
        start_ts = int(datetime.now().timestamp()) - (7 * 86400)

        # Spirit
        k_candles_spirit: List[Dict[str, Any]] = kalshi.fetch_candlesticks(
            "KXCSGOGAME", kalshi_ticker_spirit, start_ts=start_ts
        )
        print(f"Fetched {len(k_candles_spirit)} candles for Spirit")
        if k_candles_spirit:
            for c in k_candles_spirit:
                # Handle potential key differences
                ts = c.get("end_period_ts", c.get("end_period"))
                if not ts:
                    continue

                # Safe price extraction
                price_val = 0.0
                p_dict = c.get("price")
                if isinstance(p_dict, dict):
                    price_val = float(p_dict.get("close", 0))
                else:
                    price_val = float(c.get("close", 0))

                data.append(
                    {
                        "timestamp": datetime.fromtimestamp(ts),
                        "platform": "Kalshi",
                        "team": "Spirit",
                        "price": price_val / 100.0,
                    }
                )
        else:
            print("No candles for Spirit, fetching current price...")
            markets: List[MarketEvent] = kalshi.fetch_markets(
                series_ticker="KXCSGOGAME", limit=500
            )
            for m in markets:
                if m.event_id == kalshi_ticker_spirit:
                    data.append(
                        {
                            "timestamp": datetime.now(),
                            "platform": "Kalshi",
                            "team": "Spirit",
                            "price": m.last_price,
                        }
                    )
                    break

        # FaZe
        k_candles_faze: List[Dict[str, Any]] = kalshi.fetch_candlesticks(
            "KXCSGOGAME", kalshi_ticker_faze, start_ts=start_ts
        )
        print(f"Fetched {len(k_candles_faze)} candles for FaZe")
        if k_candles_faze:
            for c in k_candles_faze:
                ts = c.get("end_period_ts", c.get("end_period"))
                if not ts:
                    continue

                # Safe price extraction
                price_val = 0.0
                p_dict = c.get("price")
                if isinstance(p_dict, dict):
                    price_val = float(p_dict.get("close", 0))
                else:
                    price_val = float(c.get("close", 0))

                data.append(
                    {
                        "timestamp": datetime.fromtimestamp(ts),
                        "platform": "Kalshi",
                        "team": "FaZe",
                        "price": price_val / 100.0,
                    }
                )
        else:
            print("No candles for FaZe, fetching current price...")
            markets = kalshi.fetch_markets(series_ticker="KXCSGOGAME", limit=500)
            for m in markets:
                if m.event_id == kalshi_ticker_faze:
                    data.append(
                        {
                            "timestamp": datetime.now(),
                            "platform": "Kalshi",
                            "team": "FaZe",
                            "price": m.last_price,
                        }
                    )
                    break

    except Exception as e:
        print(f"Kalshi Fetch Error: {e}")

    # Polymarket: Dynamic Search (Disabled for speed)
    print("Skipping Polymarket search to ensure plot generation.")
    poly_event = None

    # Polymarket Data
    if poly_event:
        pass  # Placeholder for when we have real event loop if wanted
    else:
        print("Polymarket event not found. Skipping Polymarket data.")

    # 3. Plotting
    if not data:
        print("No data to plot.")
        return

    df = pd.DataFrame(data)
    print(f"Plotting {len(df)} data points...")

    plt.figure(figsize=(12, 6))

    # Plot Spirit
    spirit_data = df[df["team"] == "Spirit"]
    if not spirit_data.empty:
        for platform in spirit_data["platform"].unique():
            subset = spirit_data[spirit_data["platform"] == platform]
            plt.plot(
                subset["timestamp"],
                subset["price"],
                label=f"Spirit ({platform})",
                marker="o",
            )

    # Plot FaZe
    faze_data = df[df["team"] == "FaZe"]
    if not faze_data.empty:
        for platform in faze_data["platform"].unique():
            subset = faze_data[faze_data["platform"] == platform]
            plt.plot(
                subset["timestamp"],
                subset["price"],
                label=f"FaZe ({platform})",
                linestyle="--",
                marker="x",
            )

    plt.title("Arbitrage Analysis: Spirit vs FaZe (Blast Rivals)")
    plt.xlabel("Time")
    plt.ylabel("Price (Probability)")
    plt.legend()
    plt.grid(True)
    plt.savefig("blast_rivals_arbitrage.png")
    print("Plot saved to blast_rivals_arbitrage.png")


if __name__ == "__main__":
    analyze_blast_rivals()
