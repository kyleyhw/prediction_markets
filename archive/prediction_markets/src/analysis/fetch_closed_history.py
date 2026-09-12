import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests


def fetch_closed_history() -> None:
    """
    Fetch history for a closed Polymarket event to test archival access.
    """
    print("--- Fetching Closed Market History ---")

    # 1. Get a closed market
    url = "https://gamma-api.polymarket.com/events?limit=10&closed=true"
    try:
        resp = requests.get(url)
        data: List[Dict[str, Any]] = resp.json()

        target_id: Optional[str] = None
        target_name: Optional[str] = None

        for event in data:
            for market in event.get("markets", []):
                # Check for CLOB ID
                clob_ids_raw = market.get("clobTokenIds", [])
                clob_ids: List[str] = (
                    json.loads(clob_ids_raw)
                    if isinstance(clob_ids_raw, str)
                    else clob_ids_raw
                )

                if clob_ids:
                    target_id = str(clob_ids[0])
                    target_name = str(market.get("question", "Unknown"))
                    print(f"Found Market: {target_name}")
                    print(f"ID: {target_id}")
                    break
            if target_id:
                break

        if not target_id:
            print("No closed market with CLOB ID found.")
            return

        # 2. Fetch History (Try CLOB with Auth)
        # We need to import the collector to use its auth method
        from src.collectors.polymarket import PolymarketCollector

        poly = PolymarketCollector()

        clob_url = "https://clob.polymarket.com/prices-history"
        params: Dict[str, str] = {
            "market": target_id,
            "interval": "1h",  # Try hourly
        }

        # Construct full path for signing
        query = urlencode(params)
        full_path = f"/prices-history?{query}"

        headers: Dict[str, str] = poly._get_auth_headers("GET", full_path)
        print(f"Requesting CLOB history for {target_id}...")

        h_resp = requests.get(clob_url, params=params, headers=headers)

        if h_resp.status_code == 200:
            h_data: Dict[str, Any] = h_resp.json()
            history: List[Any] = h_data.get("history", [])
            print(f"SUCCESS! Fetched {len(history)} data points from CLOB.")
            if history:
                print(f"Sample: {history[-1]}")
        else:
            print(f"Failed: {h_resp.status_code} - {h_resp.text}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    fetch_closed_history()
