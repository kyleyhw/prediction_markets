from typing import List

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def find_blast_rivals() -> None:
    """
    Search specifically for the 'Spirit vs FaZe' match in both databases
    to find rivals or opportunities.
    """
    print("SEARCHING_POLYMARKET...")
    poly = PolymarketCollector()
    # Fetch open AND closed events
    try:
        # Fetch open
        events_open: List[MarketEvent] = poly.fetch_markets(limit=1000, closed=False)
        # Fetch closed
        events_closed: List[MarketEvent] = poly.fetch_markets(limit=1000, closed=True)

        events = events_open + events_closed

        for e in events:
            text = (e.event_name + " " + e.description).lower()
            if "spirit" in text and "faze" in text:
                msg = f"MATCH_POLY: {e.event_name} | ID: {e.event_id} | Slug: {e.url.split('/')[-1]}"
                print(msg)
                with open("blast_rivals_matches.txt", "a") as f:
                    f.write(msg + "\n")
    except Exception as e:
        print(f"Poly Error: {e}")

    print("SEARCHING_KALSHI...")
    kalshi = KalshiCollector()
    try:
        # Try generic CS2 ticker
        markets: List[MarketEvent] = kalshi.fetch_markets(
            series_ticker="KXCSGOGAME", limit=500
        )
        for m in markets:
            text = (m.event_name + " " + m.description).lower()
            if "spirit" in text and "faze" in text:
                msg = f"MATCH_KALSHI: {m.event_name} | Ticker: {m.event_id}"
                print(msg)
                with open("blast_rivals_matches.txt", "a") as f:
                    f.write(msg + "\n")
    except Exception as e:
        print(f"Kalshi Error: {e}")


if __name__ == "__main__":
    # Clear file
    with open("blast_rivals_matches.txt", "w") as f:
        f.write("")
    find_blast_rivals()
