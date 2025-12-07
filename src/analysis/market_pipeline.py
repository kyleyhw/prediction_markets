from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import pandas as pd

from src.collectors.base import MarketEvent
from src.collectors.kalshi import KalshiCollector
from src.collectors.polymarket import PolymarketCollector


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    text = text.lower()
    remove_words = ["will", "win", "the", "match", "vs", "vs.", "winner", "?"]
    for word in remove_words:
        text = (
            text.replace(f" {word} ", " ")
            .replace(f"{word} ", "")
            .replace(f" {word}", "")
        )
    return " ".join(text.split())


def similarity(a: str, b: str) -> float:
    """Calculate string similarity."""
    return SequenceMatcher(None, a, b).ratio()


def run_pipeline(category: str, poly_query: str, kalshi_ticker: str) -> None:
    print(f"--- Starting Pipeline for {category} ---")

    # 1. Fetch Kalshi Markets
    print(f"Fetching Kalshi markets for series: {kalshi_ticker}...")
    kalshi = KalshiCollector()
    k_markets: List[MarketEvent] = []
    try:
        k_markets = kalshi.fetch_markets(series_ticker=kalshi_ticker, limit=1000)
        print(f"Fetched {len(k_markets)} Kalshi markets.")
    except Exception as e:
        print(f"Kalshi Fetch Error: {e}")
        k_markets = []

    # 2. Fetch Polymarket Events
    print(f"Fetching Polymarket events for query: '{poly_query}'...")
    poly = PolymarketCollector()
    p_events: List[Dict[str, Any]] = []
    try:
        # Fetch Open
        # Since collector doesn't support q param yet in fetch_markets, we use the raw request logic here or update collector.
        # For now, let's use the raw request logic to be efficient, similar to find_poly_tag.py
        import requests

        url = "https://gamma-api.polymarket.com/events"

        # Fetch Open
        params: Dict[str, Any] = {"limit": 100, "closed": False, "q": poly_query}
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                events = res.json()
                print(f"Found {len(events)} Open Polymarket Events (Raw).")
                for e in events:
                    title = e.get("title", "")
                    if poly_query.lower() in title.lower():
                        for m in e.get("markets", []):
                            p_events.append(
                                {
                                    "event_name": m.get("question", title),
                                    "event_id": m.get("id"),
                                    "description": e.get("description", ""),
                                }
                            )
        except Exception as e:
            print(f"Open Fetch Error: {e}")

        # Fetch Closed
        params = {"limit": 100, "closed": True, "q": poly_query}
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                events = res.json()
                print(f"Found {len(events)} Closed Polymarket Events (Raw).")
                for e in events:
                    title = e.get("title", "")
                    if poly_query.lower() in title.lower():
                        for m in e.get("markets", []):
                            p_events.append(
                                {
                                    "event_name": m.get("question", title),
                                    "event_id": m.get("id"),
                                    "description": e.get("description", ""),
                                }
                            )
        except Exception as e:
            print(f"Closed Fetch Error: {e}")

        print(f"Fetched {len(p_events)} Polymarket events.")
    except Exception as e:
        print(f"Polymarket Fetch Error: {e}")

    # 3. Match Markets
    print("Matching markets...")
    matches: List[Dict[str, Any]] = []

    for k in k_markets:
        k_norm = normalize_text(k.event_name)
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0.0

        for p in p_events:
            p_val = str(p.get("event_name", ""))
            p_norm = normalize_text(p_val)
            score = similarity(k_norm, p_norm)

            if score > best_score:
                best_score = score
                best_match = p

        if best_score > 0.4 and best_match:  # Threshold
            matches.append(
                {
                    "Kalshi_Event": k.event_name,
                    "Kalshi_ID": k.event_id,
                    "Polymarket_Event": best_match["event_name"],
                    "Polymarket_ID": best_match["event_id"],
                    "Score": best_score,
                }
            )

    # 4. Output Results
    if matches:
        df = pd.DataFrame(matches)
        df = df.sort_values("Score", ascending=False)
        print("\nTop Matches:")
        print(df[["Kalshi_Event", "Polymarket_Event", "Score"]].head(10))
        df.to_csv(f"{category}_matches.csv", index=False)
        print(f"\nSaved matches to {category}_matches.csv")
    else:
        print("No matches found.")


if __name__ == "__main__":
    # Run for CS2
    run_pipeline("CS2", "Blast", "KXCSGOGAME")
