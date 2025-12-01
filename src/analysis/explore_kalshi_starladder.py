import requests
import json
from src.collectors.kalshi import KalshiCollector

def explore_kalshi_starladder():
    # Ticker from URL: kxstarladderbudapestmajor-star25
    # Series Ticker: kxstarladderbudapestmajor
    
    collector = KalshiCollector()
    
    # Try 1: Uppercase Series Ticker
    series_ticker = "KXSTARLADDERBUDAPESTMAJOR"
    print(f"Fetching Kalshi markets for series: {series_ticker}...")
    markets = collector.fetch_markets(series_ticker=series_ticker)
    
    if not markets:
        print("  No markets found with uppercase series ticker.")
        # Try 2: Direct Market Ticker Fetch (Manual Request)
        market_ticker = "kxstarladderbudapestmajor-star25"
        print(f"Fetching specific market: {market_ticker}...")
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{market_ticker}"
        try:
            resp = requests.get(url)
            if resp.status_code == 200:
                m_data = resp.json().get('market')
                if m_data:
                    print(f"  Found Market: {m_data.get('title')}")
                    # Parse it using collector's helper if possible, or just use data
                    # We need to wrap it in a list to reuse the loop below
                    # But wait, collector._parse_market expects the dict.
                    parsed = collector._parse_market(m_data)
                    markets = [parsed]
            else:
                print(f"  Failed to fetch specific market: {resp.status_code}")
        except Exception as e:
            print(f"  Error fetching specific market: {e}")

    print(f"Found {len(markets)} markets total.")
    
    for m in markets:
        print(f"  Market: {m.event_name} (ID: {m.event_id})")
        print(f"    Prices: {m.prices}")
        
        # Try to fetch candlesticks/history for this market
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{m.event_id}/candlesticks"
        params = {"limit": 100, "period_interval": 60} # 1 hour
        
        try:
            print(f"    Requesting candlesticks: {url}")
            resp = requests.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                candles = data.get('candlesticks', [])
                print(f"    Candlesticks found: {len(candles)}")
                if candles:
                    print(f"      Sample: {candles[0]}")
            else:
                print(f"    Failed to get candlesticks: {resp.status_code} - {resp.text[:100]}")
        except Exception as e:
            print(f"    Error fetching candlesticks: {e}")

if __name__ == "__main__":
    explore_kalshi_starladder()
