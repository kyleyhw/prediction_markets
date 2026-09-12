import json
from typing import Any, Dict, List, Optional

import requests

from src.collectors.polymarket import PolymarketCollector
from src.config import POLYMARKET_API_KEY


def try_fetch() -> None:
    """
    Attempt to fetch history for a specific market (Donald Trump 2024 Winner)
    using both Gamma and CLOB APIs to verify access.
    """
    print("--- Verifying Polymarket History Fetch ---")
    slug: str = "presidential-election-winner-2024"
    print(f"Target Slug: {slug}")

    poly = PolymarketCollector()

    # 1. Resolve Market ID
    print("\n1. Resolving Market ID for 'Donald Trump'...")
    event: Optional[Dict[str, Any]] = poly.fetch_event_by_slug(slug)
    if not event:
        print("Error: Event not found.")
        return

    market_id: Optional[str] = None
    for m in event.get("markets", []):
        question = str(m.get("question", ""))
        group_title = str(m.get("groupItemTitle", ""))
        if "Donald Trump" in question or "Donald Trump" in group_title:
            clob_ids_raw = m.get("clobTokenIds", "[]")
            clob_ids: List[str] = (
                json.loads(clob_ids_raw)
                if isinstance(clob_ids_raw, str)
                else clob_ids_raw
            )
            if clob_ids:
                market_id = str(clob_ids[0])
                print(f"Found Market ID (Token ID): {market_id}")
                break

    if not market_id:
        print("Error: Could not find 'Donald Trump' market ID.")
        return

    # 2. Try Public Fetch (Gamma)
    print("\n2. Attempting PUBLIC Fetch (Gamma API)...")
    gamma_url: str = "https://gamma-api.polymarket.com/prices-history"
    params: Dict[str, Any] = {
        "market": market_id,
        "interval": "1d",
        "startTs": 1704067200,  # Jan 1 2024
        "endTs": 1731196800,  # Nov 10 2024
    }
    try:
        resp = requests.get(gamma_url, params=params)
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            pts: int = len(data.get("history", []))
            print(f"Success! Fetched {pts} data points.")
        else:
            print(f"Failed: {resp.text}")
    except Exception as e:
        print(f"Exception: {e}")

    # 3. Try Private Fetch (CLOB API)
    print("\n3. Attempting PRIVATE Fetch (CLOB API)...")
    if not POLYMARKET_API_KEY:
        print("Skipping: No API Key found in config.")
        return

    # Try a 1 day range
    short_start: int = 1704067200
    short_end: int = 1704153600
    params_short: Dict[str, Any] = {
        "market": market_id,
        "interval": "1h",  # Try hourly for short range
        "startTs": short_start,
        "endTs": short_end,
    }

    try:
        clob_url: str = "https://clob.polymarket.com/prices-history"
        from urllib.parse import urlencode

        query = urlencode(params_short)
        full_path: str = f"/prices-history?{query}"

        headers: Dict[str, str] = poly._get_auth_headers("GET", full_path)
        print(f"Auth Headers Generated: {'Yes' if headers else 'No'}")

        print(f"Requesting range: {short_start} to {short_end}")
        resp_c = requests.get(clob_url, params=params_short, headers=headers)
        print(f"Status Code: {resp_c.status_code}")
        if resp_c.status_code == 200:
            data_c = resp_c.json()
            pts_c = len(data_c.get("history", []))
            print(f"Success! Fetched {pts_c} data points.")
            print(f"Sample: {data_c.get('history', [])[:2]}")
        else:
            print(f"Failed: {resp_c.text}")

    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    try_fetch()
