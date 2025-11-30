import requests
import json

def investigate_kalshi():
    print("--- Investigation 3: Fetch Specific Event Ticker ---")
    # Ticker from search result: EventKXCSGOGAME-25NOV29TYLOONIP
    # Note: The date might be in the past or future. 25NOV29 is likely Nov 29, 2025.
    ticker = "EventKXCSGOGAME-25NOV29TYLOONIP"
    url = f"https://api.elections.kalshi.com/trade-api/v2/events/{ticker}"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            print("Success! Found event.")
            data = response.json()
            event = data.get('event', {})
            print(f"Title: {event.get('title')}")
            print(f"Series Ticker: {event.get('series_ticker')}")
            print(f"Markets: {len(event.get('markets', []))}")
            if event.get('markets'):
                print(f"Sample Market: {event.get('markets')[0]}")
        else:
            print(f"Failed to fetch event {ticker}. Status: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- Investigation 4: Fetch Markets with Explicit Series Ticker ---")
    url_markets = "https://api.elections.kalshi.com/trade-api/v2/markets"
    params = {
        "series_ticker": "KXCSGOGAME",
        "limit": 100
    }
    try:
        response = requests.get(url_markets, params=params)
        data = response.json()
        markets = data.get('markets', [])
        print(f"Fetched {len(markets)} markets with series_ticker='KXCSGOGAME'.")
        
        if markets:
            print("Sample Market Details:")
            m = markets[0]
            print(f"Title: {m.get('title')}")
            print(f"Status: {m.get('status')}")
            print(f"Open Time: {m.get('open_time')}")
            print(f"Close Time: {m.get('close_time')}")
            print(f"Yes Bid: {m.get('yes_bid')}")
            print(f"Yes Ask: {m.get('yes_ask')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    investigate_kalshi()
