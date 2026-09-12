import json
from typing import Any, Dict, List, Optional

from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def find_election_markets() -> None:
    """
    Search for Presidential Election markets on Kalshi and Polymarket to discover IDs.
    """
    print("--- Finding Election Markets ---")

    # 1. Kalshi
    print("\nSearching Kalshi...")
    kalshi = KalshiCollector()
    try:
        # Search for markets in the PRES series
        markets = kalshi.fetch_markets(limit=1000, series_ticker="PRES")
        found: bool = False
        for m in markets:
            # Look for the main winner market
            if (
                "Presidential Election" in m.event_name
                and "Winner" in m.event_name
                and "2024" in m.event_name
            ):
                print(f"Potential Kalshi Match: {m.event_name}")
                print(f"  ID: {m.event_id}")
                print(f"  Start: {m.start_time}")
                found = True
        if not found:
            print(
                "No exact match found for 'Presidential Election Winner 2024' "
                "in PRES series."
            )
            # Try broader search
            for m in markets:
                if "Trump" in m.event_name or "Harris" in m.event_name:
                    print(f"  Partial Match: {m.event_name} ({m.event_id})")
    except Exception as e:
        print(f"Kalshi Error: {e}")

    # 2. Polymarket
    print("\nSearching Polymarket...")
    poly = PolymarketCollector()
    try:
        slug: str = "presidential-election-winner-2024"
        print(f"Fetching event: {slug}")
        event: Optional[Dict[str, Any]] = poly.fetch_event_by_slug(slug)
        if event:
            print(f"Event Found: {event.get('title')}")
            for m in event.get("markets", []):
                name = m.get("question") or m.get("groupItemTitle")
                print(f"  Outcome: {name}")
                print(f"  Market ID: {m.get('id')}")
                clob_ids_raw = m.get("clobTokenIds", "[]")
                clob_ids: List[str] = (
                    json.loads(clob_ids_raw)
                    if isinstance(clob_ids_raw, str)
                    else clob_ids_raw
                )
                print(f"  CLOB Token IDs: {clob_ids}")
    except Exception as e:
        print(f"Polymarket Error: {e}")


if __name__ == "__main__":
    find_election_markets()
