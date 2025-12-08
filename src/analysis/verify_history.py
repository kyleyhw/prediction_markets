import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def verify_history() -> None:
    print("Initializing Collectors...")
    poly = PolymarketCollector()
    kalshi = KalshiCollector()

    # 1. Find Closed Markets
    print("\n--- Finding Closed Markets ---")

    # Kalshi
    print("Searching Kalshi for closed markets...")
    k_market: Optional[MarketEvent] = None
    try:
        # Try a different series or just search generally again with a better filter
        # Let's try "KXCSGOGAME" again but look for *any* closed one
        markets: List[MarketEvent] = kalshi.fetch_markets(
            limit=100, series_ticker="KXCSGOGAME"
        )
        for m in markets:
            # Check if start time is in the past to guess it might be closed/active
            now = (
                datetime.now().astimezone()
                if m.start_time and m.start_time.tzinfo
                else datetime.now()
            )
            start = m.start_time
            if start and start < now:
                k_market = m
                print(
                    f"Found Kalshi Market (Past Start): {m.event_name} ({m.event_id})"
                )
                break
    except Exception as e:
        print(f"Kalshi Search Error: {e}")

    # Polymarket
    print("Searching Polymarket for closed markets...")
    p_market: Optional[MarketEvent] = None
    try:
        # Fetch Active Market for Proof
        print("Fetching an ACTIVE market for control...")
        active_markets: List[MarketEvent] = poly.fetch_markets(limit=1)
        if active_markets:
            a_market = active_markets[0]
            print(f"Found Active Polymarket Market: {a_market.event_name}")
            slug = a_market.url.split("/")[-1]
            raw_event: Optional[Dict[str, Any]] = poly.fetch_event_by_slug(slug)
            if raw_event:
                target_market: Optional[Dict[str, Any]] = None
                for m_dict in raw_event.get("markets", []):
                    # Compare strings safely
                    if str(m_dict.get("question")) == a_market.event_name:
                        target_market = m_dict
                        break
                if target_market:
                    clob_ids_raw = target_market.get("clobTokenIds", "[]")
                    clob_ids: List[str] = (
                        json.loads(clob_ids_raw)
                        if isinstance(clob_ids_raw, str)
                        else clob_ids_raw
                    )
                    if clob_ids:
                        print(
                            f"Fetching history for ACTIVE market "
                            f"{a_market.event_name} (ID: {clob_ids[0]})..."
                        )
                        h: List[Dict[str, Any]] = poly.fetch_price_history(clob_ids[0])
                        print(f"Active Market History: {len(h)} points found.")

                        if h:
                            df = pd.DataFrame(h)
                            if "t" in df.columns and "p" in df.columns:
                                df["timestamp"] = pd.to_datetime(df["t"], unit="s")
                                df["price"] = df["p"]
                                plt.figure(figsize=(10, 5))
                                plt.plot(df["timestamp"], df["price"], label="Price")
                                plt.title(
                                    f"Active Polymarket History: {a_market.event_name}"
                                )
                                plt.xlabel("Date")
                                plt.ylabel("Price")
                                plt.legend()
                                plt.grid(True)
                                plt.savefig("polymarket_active_history.png")
                                print("Saved polymarket_active_history.png")
                    else:
                        print("No CLOB ID for active market.")

                # Assign p_market for later
                p_market = a_market

    except Exception as e:
        print(f"Polymarket Search Error: {e}")

    # 2. Fetch History (Kalshi)
    print("\n--- Fetching History ---")

    if k_market:
        print(f"Fetching history for Kalshi: {k_market.event_id}")
        try:
            # Fetch last 365 days to be safe
            end_ts = int(datetime.now().timestamp())
            start_ts = end_ts - (365 * 86400)

            # Use series ticker from market ID if possible?
            series_ticker = (
                k_market.event_id.split("-")[0]
                if "-" in k_market.event_id
                else "KXCSGOGAME"
            )
            print(f"Using Series Ticker: {series_ticker}")

            candles: List[Dict[str, Any]] = kalshi.fetch_candlesticks(
                series_ticker, k_market.event_id, start_ts=start_ts
            )
            print(f"Fetched {len(candles)} candles from Kalshi.")

            if candles:
                df = pd.DataFrame(candles)

                # Safe timestamp
                ts_series = df.get("end_period", df.get("end_period_ts"))
                if ts_series is not None:
                    df["timestamp"] = pd.to_datetime(ts_series, unit="s")

                    # Safe price
                    def get_price(row: pd.Series) -> float:
                        p_dict = row.get("price")
                        if isinstance(p_dict, dict):
                            return float(p_dict.get("close", 0))
                        if "close" in row:
                            return float(row["close"])
                        return 0.0

                    df["price"] = df.apply(get_price, axis=1) / 100.0

                    plt.figure(figsize=(10, 5))
                    plt.plot(df["timestamp"], df["price"], label="Close Price")
                    plt.title(f"Kalshi History: {k_market.event_name}")
                    plt.xlabel("Date")
                    plt.ylabel("Price")
                    plt.legend()
                    plt.grid(True)
                    plt.savefig("kalshi_history_verification.png")
                    print("Saved kalshi_history_verification.png")
        except Exception as e:
            print(f"Kalshi History Error: {e}")

    # 3. Fetch History (Polymarket - Closed/Active reused)
    if p_market:
        print(f"Fetching history for Polymarket: {p_market.event_name}")
        try:
            slug = p_market.url.split("/")[-1]
            print(f"Fetching full event details for slug: {slug}")
            raw_event = poly.fetch_event_by_slug(slug)

            if raw_event:
                target_market = None
                # Re-find the market we selected
                for m_dict in raw_event.get("markets", []):
                    if str(m_dict.get("question")) == p_market.event_name:
                        target_market = m_dict
                        break

                if target_market:
                    clob_ids_raw = target_market.get("clobTokenIds", "[]")
                    clob_ids = (
                        json.loads(clob_ids_raw)
                        if isinstance(clob_ids_raw, str)
                        else clob_ids_raw
                    )
                    if clob_ids:
                        token_id = str(clob_ids[0])
                        print(f"Found CLOB Token ID: {token_id}")

                        # Fetch daily history for longer range
                        history: List[Dict[str, Any]] = poly.fetch_price_history(
                            token_id, interval="1d"
                        )
                        print(f"Fetched {len(history)} data points from Polymarket.")

                        if history:
                            df = pd.DataFrame(history)
                            if "t" in df.columns and "p" in df.columns:
                                df["timestamp"] = pd.to_datetime(df["t"], unit="s")
                                df["price"] = df["p"]

                                plt.figure(figsize=(10, 5))
                                plt.plot(df["timestamp"], df["price"], label="Price")
                                plt.title(
                                    f"Polymarket History (Re-Verified): "
                                    f"{p_market.event_name}"
                                )
                                plt.xlabel("Date")
                                plt.ylabel("Price")
                                plt.legend()
                                plt.grid(True)
                                plt.savefig("polymarket_history_verification_2.png")
                                print("Saved polymarket_history_verification_2.png")
                            else:
                                print(f"Unknown history format: {history[0]}")
                    else:
                        print("No CLOB Token IDs found for this market.")
                else:
                    print("Could not find matching market in event details.")
            else:
                print("Could not fetch raw event details.")

        except Exception as e:
            print(f"Polymarket History Error: {e}")


if __name__ == "__main__":
    verify_history()
