from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def test_polymarket():
    print("Testing Polymarket Collector...")
    collector = PolymarketCollector()
    # Using a known tag for Esports or just fetching recent events
    # Tag ID for 'Esports' might need to be looked up, but let's try fetching general events first or search logic.
    # For now, let's try without tag to see if it works, or use a known one if we had it.
    # The search result mentioned we need a tag ID.
    # Let's try fetching a few events and printing them.
    markets = collector.fetch_markets(limit=5)
    print(f"Fetched {len(markets)} markets from Polymarket.")
    if markets:
        print(f"Sample: {markets[0]}")


def test_kalshi():
    print("\nTesting Kalshi Collector (Search)...")
    collector = KalshiCollector()
    # Fetch more markets to search for CS2
    markets = collector.fetch_markets(limit=100)
    cs_markets = [
        m
        for m in markets
        if "Counter-Strike" in m.event_name
        or "CS2" in m.event_name
        or "CS:GO" in m.event_name
    ]

    print(f"Found {len(cs_markets)} CS2 related markets.")
    if cs_markets:
        print(f"Sample CS2 Market: {cs_markets[0]}")
        print(f"Ticker: {cs_markets[0].event_id}")


if __name__ == "__main__":
    test_polymarket()
    test_kalshi()
