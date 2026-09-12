from datetime import datetime
from typing import Any, Dict, List

import requests

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector


def find_all_trump_markets() -> None:
    print("--- Searching for all 'Trump' markets on Kalshi ---")
    kalshi = KalshiCollector()

    # Fetch a large number of markets to scan history
    # We can't easily filter by date in the fetch, so we fetch all in the series
    # or search text if possible.
    # The current collector `fetch_markets` takes a series_ticker.
    # Let's try "PRES" series first, then maybe just a broad limit if possible
    # (though limit is usually per request).

    all_markets: List[MarketEvent] = []

    # Strategy 1: PRES series with explicit status
    print("Scanning PRES series...")
    statuses: List[str] = ["open", "closed", "settled"]
    for status in statuses:
        print(f"  Status: {status}")
        try:
            # We need to modify fetch_markets to accept status or pass it in kwargs
            # if supported.
            # The current fetch_markets implementation hardcodes params.
            # We should probably use the requests directly here or modify the collector.
            # Let's use the collector's session/base_url but manually call to be
            # flexible.
            endpoint = f"{kalshi.BASE_URL}/markets"
            params = {"limit": 1000, "series_ticker": "PRES", "status": status}
            session = getattr(kalshi, "session", requests)
            resp = session.get(endpoint, params=params)
            data: Dict[str, Any] = resp.json()
            for m_dict in data.get("markets", []):
                m = kalshi._parse_market(m_dict)
                all_markets.append(m)
        except Exception as e:
            print(f"    Error: {e}")

    # Strategy 2: KXPRES series
    print("Scanning KXPRES series...")
    for status in statuses:
        try:
            endpoint = f"{kalshi.BASE_URL}/markets"
            params = {"limit": 1000, "series_ticker": "KXPRES", "status": status}
            # We can use requests direct if session not avail, but we try session first
            session = getattr(kalshi, "session", requests)
            resp = session.get(endpoint, params=params)
            data: Dict[str, Any] = resp.json()
            for m_dict in data.get("markets", []):
                m = kalshi._parse_market(m_dict)
                all_markets.append(m)
        except Exception as e:
            print(f"    Error: {e}")

    print(f"Found {len(all_markets)} total markets in election series.")

    # Filter for "Trump" and print details
    trump_markets: List[MarketEvent] = []
    for m in all_markets:
        if "Trump" in m.event_name or "Trump" in m.event_id:
            trump_markets.append(m)

    # Sort by start time
    trump_markets.sort(key=lambda x: x.start_time or datetime.min)

    print(f"\nFound {len(trump_markets)} Trump-related markets:")
    for m in trump_markets:
        print(f"  Date: {m.start_time} | ID: {m.event_id} | Name: {m.event_name}")


if __name__ == "__main__":
    find_all_trump_markets()
