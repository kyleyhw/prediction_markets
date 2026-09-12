from typing import List

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def dump_markets() -> None:
    print("Starting dump...")
    with open("all_markets_dump.txt", "w", encoding="utf-8") as f:
        f.write("STARTING DUMP\n")
        f.flush()

        # Polymarket
        print("Fetching Polymarket...")
        try:
            poly = PolymarketCollector()
            # Fetch small batch first to test
            events: List[MarketEvent] = poly.fetch_markets(limit=10, closed=False)
            f.write(f"Fetched {len(events)} Poly events\n")
            f.flush()

            for e in events:
                try:
                    line = (
                        f"POLY | {e.event_name} | {e.description} | "
                        f"ID: {e.event_id} | Slug: {e.url}\n"
                    )
                    f.write(line)
                    f.flush()
                except Exception as inner_e:
                    print(f"Skipping event: {inner_e}")
        except Exception as e:
            f.write(f"POLY ERROR: {e}\n")
            f.flush()
            print(f"POLY ERROR: {e}")

        # Kalshi
        print("Fetching Kalshi...")
        try:
            kalshi = KalshiCollector()
            markets: List[MarketEvent] = kalshi.fetch_markets(
                series_ticker="KXCSGOGAME", limit=50
            )
            f.write(f"Fetched {len(markets)} Kalshi markets\n")
            f.flush()

            for m in markets:
                try:
                    line = (
                        f"KALSHI | {m.event_name} | {m.description} | "
                        f"Ticker: {m.event_id}\n"
                    )
                    f.write(line)
                    f.flush()
                except Exception as inner_e:
                    print(f"Skipping market: {inner_e}")
        except Exception as e:
            f.write(f"KALSHI ERROR: {e}\n")
            f.flush()
            print(f"KALSHI ERROR: {e}")


if __name__ == "__main__":
    dump_markets()
