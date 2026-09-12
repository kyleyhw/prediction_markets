import json
import re
from typing import Any, Dict, List

import requests


def inspect_page() -> None:
    url: str = "https://polymarket.com/event/presidential-election-winner-2024?tid=1764896519091"
    print(f"Fetching {url}...")

    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
    }

    try:
        resp = requests.get(url, headers=headers)
        print(f"Status: {resp.status_code}")

        if resp.status_code != 200:
            print("Failed to fetch page.")
            return

        html: str = resp.text
        print(f"Page size: {len(html)} bytes")

        with open("page_dump.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved page_dump.html")

        # Look for Next.js data
        # <script id="__NEXT_DATA__" type="application/json">
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html
        )
        if match:
            print("Found __NEXT_DATA__!")
            json_str = match.group(1)
            data: Dict[str, Any] = json.loads(json_str)

            # Save to file for inspection (optional, but good for debugging)
            # with open("next_data.json", "w") as f:
            #     json.dump(data, f, indent=2)

            # Search for "history" or "prices" in the data
            # This is a large object, so we need to be careful.

            # Recursive search for market ID
            def find_key(obj: Any, key: str, path: str = "") -> None:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k == key:
                            print(f"Found key '{key}' at {path}.{k}")
                        if isinstance(v, (dict, list)):
                            find_key(v, key, f"{path}.{k}")
                elif isinstance(obj, list):
                    for i, v in enumerate(obj):
                        find_key(v, key, f"{path}[{i}]")

            # print("Searching for market ID in NEXT_DATA...")
            # find_key(data, market_id) # This might be a value, not a key.

            # Let's search for the string "history"
            # print("Searching for 'history' key...")
            # find_key(data, "history")

            # Let's try to extract the specific market data if possible
            # Usually in props -> pageProps -> dehydratedState -> queries

            queries: List[Dict[str, Any]] = (
                data.get("props", {})
                .get("pageProps", {})
                .get("dehydratedState", {})
                .get("queries", [])
            )
            print(f"Found {len(queries)} queries in dehydratedState.")

            found_history: bool = False
            for q in queries:
                query_key = q.get("queryKey", [])
                # Check if it looks like a history query
                # e.g. ['price-history', ...]
                if "price-history" in str(query_key) or "history" in str(query_key):
                    print(f"Found History Query: {query_key}")
                    state: Any = q.get("state", {}).get("data", {})
                    if state:
                        print("  Data found in state!")
                        # print(f"  Data keys: {state.keys()}")
                        if isinstance(state, list):
                            print(f"  Data is a list of length {len(state)}")
                            print(f"  Sample: {state[:2]}")
                            found_history = True
                        elif isinstance(state, dict) and "history" in state:
                            # Cast list to list to satisfy typing if needed (though
                            # Python runtime is dynamic)
                            hist_list = state["history"]
                            if isinstance(hist_list, list):
                                print(
                                    f"  Data has 'history' key with length "
                                    f"{len(hist_list)}"
                                )
                            found_history = True

            if not found_history:
                print("No obvious history data found in NEXT_DATA queries.")

        else:
            print("__NEXT_DATA__ not found.")

    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    inspect_page()
