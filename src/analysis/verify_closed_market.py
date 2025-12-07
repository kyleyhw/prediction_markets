from typing import Any, Dict, List, Optional

from src.collectors.base import MarketEvent
from src.collectors.polymarket import PolymarketCollector


def verify_closed() -> None:
    """
    Search for a closed market on Polymarket and verify that we can fetch its history.
    """
    print("--- Finding a Closed Market ---")
    poly = PolymarketCollector()

    # Fetch a few closed markets
    print("Fetching closed markets...", flush=True)
    markets: List[MarketEvent] = poly.fetch_markets(limit=20, closed=True)
    print(
        f"Fetch complete. Found {len(markets) if markets else 0} markets.", flush=True
    )

    if not markets:
        print("No closed markets found via API.")
        return

    print(f"Found {len(markets)} closed markets. Picking one to test...")

    # Pick a random one, preferably with volume so it has history
    target_market: Optional[MarketEvent] = None
    for m in markets:
        if m.volume > 1000:  # Filter for some activity
            target_market = m
            break

    if not target_market:
        target_market = markets[0]  # Fallback

    print(f"Testing Market: {target_market.event_name}")
    print(f"ID: {target_market.event_id}")
    print(f"Volume: ${target_market.volume:,.2f}")

    # Fetch History
    print("\nFetching History...")
    try:
        # We'll use the public method first (Gamma) as that's what we want to prove works for "normal" closed markets.
        # The collector tries CLOB first then Gamma.

        history: List[Dict[str, Any]] = poly.fetch_price_history(
            target_market.event_id, interval="1d"
        )

        if history:
            print(f"SUCCESS! Fetched {len(history)} data points.")
            print(f"Sample: {history[:2]}")
        else:
            print("Failed: Returned empty history.")

    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    verify_closed()
