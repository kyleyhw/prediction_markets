import requests
import json

def find_polymarket_tag():
    print("--- Polymarket Tag Discovery (By Slug) ---")
    # Fetch specific event to get tags
    slug = "english-premier-league-winner"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        if data:
            event = data[0]
            print(f"Found Event: {event.get('title')}")
            tags = event.get('tags', [])
            print(f"Tags: {tags}")
            
            for tag in tags:
                # Tag might be an object or ID
                if isinstance(tag, dict):
                    print(f"  Tag: {tag.get('label')} (ID: {tag.get('id')})")
                else:
                    # Fetch tag details if it's an ID
                    try:
                        tag_resp = requests.get(f"https://gamma-api.polymarket.com/tags/{tag}")
                        if tag_resp.status_code == 200:
                            t = tag_resp.json()
                            print(f"  Tag: {t.get('label')} (ID: {tag})")
                    except:
                        pass
        else:
            print(f"Event slug '{slug}' not found.")

    except Exception as e:
        print(f"Polymarket Error: {e}")

def find_kalshi_ticker():
    print("\n--- Kalshi Series Ticker Discovery (Limit 100) ---")
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    params = {"limit": 100} 
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        markets = data.get('markets', [])
        print(f"Fetched {len(markets)} markets.")
        
        for m in markets:
            title = m.get('title', '')
            st = m.get('series_ticker')
            if "Premier" in title or "Soccer" in title:
                print(f"Found Candidate: {title} | Series: {st}")

    except Exception as e:
        print(f"Kalshi Error: {e}")

if __name__ == "__main__":
    find_polymarket_tag()
    find_kalshi_ticker()
