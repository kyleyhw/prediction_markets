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
        
        print(f"Scanning {len(data)} events... Printing first 5:")
        count = 0
        for event in data:
            if count >= 5: break
            print(f"Found Event: {event.get('title')} (ID: {event.get('id')})")
            for m in event.get('markets', []):
                # Try to get CLOB Token ID for history
                clob_ids = json.loads(m.get('clobTokenIds', '[]')) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
                mid = clob_ids[0] if clob_ids else m.get('id')
                print(f"    Market: {m.get('question')} (ID: {mid})")
            count += 1
        
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
            if "starladder" in title or "budapest" in title:
                print(f"Found Candidate: {m.get('title')} | Series: {st} | Ticker: {m.get('ticker')}")
                found = True
        
        if not found:
            print("No 'Blast' or 'Rivals' markets found in the last 500.")

    except Exception as e:
        print(f"Kalshi Error: {e}")

if __name__ == "__main__":
    find_polymarket_tag()
    find_kalshi_ticker()
