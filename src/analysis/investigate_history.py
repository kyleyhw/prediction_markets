import time
from typing import Any, Dict, List

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def investigate_polymarket_history() -> None:
    print("\n--- Investigating Polymarket History ---")
    poly = PolymarketCollector()

    # 1. Fetch a CLOSED market
    print("Fetching a closed market...")
    markets: List[MarketEvent] = poly.fetch_markets(limit=5, closed=True)
    if not markets:
        print("No closed markets found via Gamma API.")
        return

    market = markets[0]
    print(f"Testing with Market: {market.event_name} (ID: {market.event_id})")

    # 2. Try fetching history via CLOB (requires Token ID)
    print(f"Attempting fetch_price_history with ID: {market.event_id}")
    try:
        history: List[Dict[str, Any]] = poly.fetch_price_history(
            market.event_id, interval="1d"
        )
        print(f"Success! Retrieved {len(history)} data points.")
        print(f"Sample: {history[0] if history else 'Empty'}")
    except Exception as e:
        print(f"Failed: {e}")


def investigate_kalshi_history() -> None:
    print("\n--- Investigating Kalshi History ---")
    kalshi = KalshiCollector()

    # 1. Try to find a market that is likely closed or old
    # The public API might not let us filter by 'closed' easily in the search endpoint we use.
    # Let's try to fetch candlesticks for a known old series or just the one we were looking at.

    series = "KXSTARLADDERBUDAPESTMAJOR"
    market_ticker = "KXSTARLADDERBUDAPESTMAJOR-STAR25-B8"  # From previous logs

    print(f"Testing with Market: {market_ticker}")

    # 2. Fetch History
    # Start time: 1 week ago
    start_ts: int = int(time.time()) - (7 * 24 * 60 * 60)

    try:
        history: List[Dict[str, Any]] = kalshi.fetch_candlesticks(
            series, market_ticker, start_ts=start_ts
        )
        print(f"Success! Retrieved {len(history)} data points.")
        print(f"Sample: {history[0] if history else 'Empty'}")
    except Exception as e:
        print(f"Failed: {e}")


if __name__ == "__main__":
    investigate_polymarket_history()
    investigate_kalshi_history()
