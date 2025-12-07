import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd

from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def fetch_election_history() -> None:
    """
    Fetch and plot the 2024 Presidential Election history for Donald Trump
    from both Kalshi and Polymarket.
    """
    print("--- Fetching 2024 Election History ---", flush=True)
    kalshi = KalshiCollector()
    poly = PolymarketCollector()

    # Time Range: Jan 1, 2024 to Nov 6, 2024 (Post-Election)
    start_ts: int = int(datetime(2024, 1, 1).timestamp())
    end_ts: int = int(datetime(2024, 11, 10).timestamp())

    # 1. Kalshi Data (Pagination)
    print("\nFetching Kalshi Data (PRES-2024-DJT)...", flush=True)
    k_candles: List[Dict[str, Any]] = []
    current_start: int = start_ts

    # Kalshi limit is 5000. 1 hour candles = 24 per day. 300 days = 7200 candles.
    # We need to paginate by calculating a chunk end time.
    # 5000 hours is ~200 days. Let's do 90 day chunks to be safe.
    chunk_size_sec: int = 90 * 24 * 3600

    print(f"  Start TS: {current_start}, End TS: {end_ts}", flush=True)
    while current_start < end_ts:
        chunk_end: int = min(current_start + chunk_size_sec, end_ts)
        print(
            f"  Fetching from {datetime.fromtimestamp(current_start)} to {datetime.fromtimestamp(chunk_end)}...",
            flush=True,
        )
        try:
            # Ticker: PRES-2024-DJT (Donald Trump)
            # Series: PRES
            c: List[Dict[str, Any]] = kalshi.fetch_candlesticks(
                "PRES",
                "PRES-2024-DJT",
                start_ts=current_start,
                end_ts=chunk_end,
                period_interval=60,
            )
            if not c:
                print("    No candles returned for this chunk.")
                current_start = chunk_end + 1
                continue

            k_candles.extend(c)
            print(f"    Got {len(c)} candles.")

            # Update start for next page
            current_start = chunk_end + 1

        except Exception as e:
            print(f"  Kalshi Fetch Error: {e}", flush=True)
            break

    print(f"Fetched {len(k_candles)} total candles from Kalshi.")

    # 2. Polymarket Data
    print("\nFetching Polymarket Data (Donald Trump)...")
    p_history: List[Dict[str, Any]] = []
    try:
        # Get Token ID
        slug: str = "presidential-election-winner-2024"
        event: Optional[Dict[str, Any]] = poly.fetch_event_by_slug(slug)
        token_id: Optional[str] = None
        if event:
            for m in event.get("markets", []):
                question = str(m.get("question", ""))
                group_title = str(m.get("groupItemTitle", ""))
                if "Donald Trump" in question or "Donald Trump" in group_title:
                    clob_ids_raw = m.get("clobTokenIds", "[]")
                    clob_ids: List[str] = (
                        json.loads(clob_ids_raw)
                        if isinstance(clob_ids_raw, str)
                        else clob_ids_raw
                    )
                    if clob_ids:
                        token_id = str(clob_ids[0])
                        break

        if token_id:
            print(f"  Found Token ID: {token_id}")
            # Fetch History (Daily to avoid overload, or Hourly if possible)
            # Public API might fail for closed. If so, we can't do much.
            # Let's try '1d' first as it's lighter.
            h: List[Dict[str, Any]] = poly.fetch_price_history(
                token_id, start_ts=start_ts, end_ts=end_ts, interval="1d"
            )
            p_history = h
            print(f"  Fetched {len(p_history)} data points.")
        else:
            print("  Could not find Polymarket Token ID.")

    except Exception as e:
        print(f"  Polymarket Fetch Error: {e}")

    # 3. Plotting
    print("\nPlotting...")
    plt.figure(figsize=(12, 6))

    # Kalshi Plot
    if k_candles:
        df_k = pd.DataFrame(k_candles)
        # Helper for extracting timestamp safely
        ts_series = df_k.get("end_period", df_k.get("end_period_ts"))
        if ts_series is not None:
            df_k["timestamp"] = pd.to_datetime(ts_series, unit="s")

            # Helper for extracting price safely

            def get_price(row: pd.Series) -> float:
                # Try getting 'close' from 'price' dict
                p_dict = row.get("price")
                if isinstance(p_dict, dict):
                    close_val = p_dict.get("close")
                    if close_val is not None:
                        return float(close_val)

                # Try direct 'close' (sometimes Flattened)
                if "close" in row:
                    return float(row["close"])

                return 0.0

            df_k["price"] = df_k.apply(get_price, axis=1) / 100.0
            plt.plot(
                df_k["timestamp"],
                df_k["price"],
                label="Kalshi (Trump)",
                color="blue",
                alpha=0.7,
            )

    # Polymarket Plot
    if p_history:
        df_p = pd.DataFrame(p_history)
        if "t" in df_p.columns and "p" in df_p.columns:
            df_p["timestamp"] = pd.to_datetime(df_p["t"], unit="s")
            df_p["price"] = df_p["p"]
            plt.plot(
                df_p["timestamp"],
                df_p["price"],
                label="Polymarket (Trump)",
                color="orange",
                alpha=0.7,
            )

    plt.title("2024 US Presidential Election: Trump Win Probability")
    plt.xlabel("Date")
    plt.ylabel("Price (Probability)")
    plt.legend()
    plt.grid(True)
    plt.ylim(0, 1.05)

    output_file = "election_2024_history.png"
    plt.savefig(output_file)
    print(f"Saved plot to {output_file}")


if __name__ == "__main__":
    fetch_election_history()
