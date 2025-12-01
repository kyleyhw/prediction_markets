import requests
import json

def find_polymarket_tag():
    print("--- Polymarket Tag Discovery (By Query) ---")
    # Search for events with "Blast"
    url = "https://gamma-api.polymarket.com/events"
    params = {"limit": 500, "closed": "true"} # Increase limit
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        print(f"Scanning {len(data)} events for CS2/Blast...")
        found = False
        for event in data:
            title = event.get('title', '').lower()
            if "blast" in title or "rivals" in title or "cs2" in title or "counter-strike" in title:
                print(f"Found Event: {event.get('title')} (ID: {event.get('id')})")
                print(f"  Slug: {event.get('slug')}")
                for m in event.get('markets', []):
                    print(f"    Market: {m.get('question')} (ID: {m.get('id')})")
                found = True
        
        if not found:
            print("No CS2/Blast events found in the last 500.")

    except Exception as e:
        print(f"Polymarket Error: {e}")

def find_kalshi_ticker():
    print("\n--- Kalshi Series Ticker Discovery (Limit 500) ---")
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    params = {"limit": 500, "status": "closed"} # Increase limit
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        markets = data.get('markets', [])
        print(f"Fetched {len(markets)} markets.")
        
        found = False
        for m in markets:
            title = m.get('title', '').lower()
            st = m.get('series_ticker')
            if "blast" in title or "rivals" in title or "cs2" in title or "counter-strike" in title:
                print(f"Found Candidate: {m.get('title')} | Series: {st} | Ticker: {m.get('ticker')}")
                found = True
        
        if not found:
            print("No 'Blast' or 'Rivals' markets found in the last 500.")

    except Exception as e:
        print(f"Kalshi Error: {e}")

if __name__ == "__main__":
    find_polymarket_tag()
    find_kalshi_ticker()
