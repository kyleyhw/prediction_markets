import json
from typing import Any, Dict, List, Optional

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def audit_apis() -> None:
    print("--- Polymarket Raw Data (Starladder) ---")
    poly = PolymarketCollector()
    p_event: Optional[Dict[str, Any]] = poly.fetch_event_by_slug(
        "starladder-budapest-major-2025-winner"
    )
    if p_event:
        # Get first market
        markets = p_event.get("markets", [])
        if markets:
            m = markets[0]
            print(json.dumps(m, indent=2))

            # Get Orderbook
            clob_ids_raw = m.get("clobTokenIds", "[]")
            clob_ids: List[str] = (
                json.loads(clob_ids_raw)
                if isinstance(clob_ids_raw, str)
                else clob_ids_raw
            )
            if clob_ids:
                print("\n--- Polymarket Orderbook ---")
                book: Dict[str, Any] = poly.fetch_orderbook(clob_ids[0])
                print(json.dumps(book, indent=2))

    print("\n\n--- Kalshi Raw Data (Starladder) ---")
    kalshi = KalshiCollector()
    k_markets: List[MarketEvent] = kalshi.fetch_markets(
        series_ticker="KXSTARLADDERBUDAPESTMAJOR"
    )
    if k_markets:
        # Get first market raw data (we need to access the raw dict if possible,
        # but the collector returns objects. Let's inspect the object attributes)
        m_obj = k_markets[0]
        print(m_obj.__dict__)


if __name__ == "__main__":
    audit_apis()
