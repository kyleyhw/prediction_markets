import json
from src.collectors.polymarket import PolymarketCollector
from src.collectors.kalshi import KalshiCollector

def audit_apis():
    print("--- Polymarket Raw Data (Starladder) ---")
    poly = PolymarketCollector()
    p_event = poly.fetch_event_by_slug("starladder-budapest-major-2025-winner")
    if p_event:
        # Get first market
        m = p_event['markets'][0]
        print(json.dumps(m, indent=2))
        
        # Get Orderbook
        clob_ids = json.loads(m.get('clobTokenIds', '[]')) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
        if clob_ids:
            print("\n--- Polymarket Orderbook ---")
            book = poly.fetch_orderbook(clob_ids[0])
            print(json.dumps(book, indent=2))

    print("\n\n--- Kalshi Raw Data (Starladder) ---")
    kalshi = KalshiCollector()
    k_markets = kalshi.fetch_markets(series_ticker="KXSTARLADDERBUDAPESTMAJOR")
    if k_markets:
        # Get first market raw data (we need to access the raw dict if possible, 
        # but the collector returns objects. Let's inspect the object attributes)
        m = k_markets[0]
        print(m.__dict__)

if __name__ == "__main__":
    audit_apis()
