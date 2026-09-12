from typing import List

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector


def find_kalshi_blast() -> None:
    print("SEARCHING_KALSHI_ONLY...")
    kalshi = KalshiCollector()
    try:
        # Fetch ALL markets (limit 1000)
        # We can't easily fetch ALL without pagination or series, but let's try a
        # few common series or just 'closed' if possible.
        # The collector fetch_markets uses series_ticker.
        # Let's try 'KXCSGOGAME' again but print ALL titles to see what's there.
        markets: List[MarketEvent] = kalshi.fetch_markets(
            series_ticker="KXCSGOGAME", limit=100
        )
        print(f"Fetched {len(markets)} markets.")
        for m in markets:
            print(f"  {m.event_name} ({m.event_id})")

    except Exception as e:
        print(f"Kalshi Error: {e}")


if __name__ == "__main__":
    find_kalshi_blast()
