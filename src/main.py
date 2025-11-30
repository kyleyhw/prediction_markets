import os
import json
import pandas as pd
from datetime import datetime
from src.collectors.polymarket import PolymarketCollector
from src.collectors.kalshi import KalshiCollector

DATA_DIR = "data"
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")

def save_raw_data(data, platform, timestamp):
    filename = f"{platform}_{timestamp}.json"
    filepath = os.path.join(RAW_DIR, filename)
    with open(filepath, "w") as f:
        json.dump([d.to_dict() for d in data], f, indent=2)
    print(f"Saved raw data to {filepath}")

def save_processed_data(all_markets, timestamp):
    # Flatten data for CSV
    rows = []
    for market in all_markets:
        base_dict = market.to_dict()
        # We might want to explode outcomes/prices for easier analysis, 
        # or keep them as stringified lists. For now, let's keep as is but ensure basic types.
        # Actually, for CSV, lists are messy. Let's just save the main fields.
        # Or better, save a row per outcome?
        # Let's save one row per market, with outcomes/prices as JSON strings.
        base_dict['outcomes'] = json.dumps(base_dict['outcomes'])
        base_dict['prices'] = json.dumps(base_dict['prices'])
        rows.append(base_dict)
    
    df = pd.DataFrame(rows)
    filename = f"markets_{timestamp}.csv"
    filepath = os.path.join(PROCESSED_DIR, filename)
    df.to_csv(filepath, index=False)
    print(f"Saved processed data to {filepath}")

from src.config import MARKET_CONFIG

def main():
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    all_markets = []

    for category, config in MARKET_CONFIG.items():
        print(f"\n--- Processing Category: {category} ---")
        
        # Polymarket
        print(f"Fetching Polymarket data for {category}...")
        poly_collector = PolymarketCollector()
        poly_tag = config.get("polymarket_tag_id")
        
        # If tag is provided, use it. If None (CS2), we might need to fetch all or use keywords (not implemented in collector yet)
        # For now, if tag is None, we fetch a batch of recent/trending (limit 100) and maybe filter?
        # Or just fetch generic.
        
        if poly_tag:
            poly_markets = poly_collector.fetch_markets(tag_id=poly_tag, limit=100)
        else:
            # Fallback for CS2 if no tag known yet, fetch generic
            poly_markets = poly_collector.fetch_markets(limit=100)
            
        save_raw_data(poly_markets, f"polymarket_{category}", timestamp)
        all_markets.extend(poly_markets)
        
        # Kalshi
        print(f"Fetching Kalshi data for {category}...")
        kalshi_collector = KalshiCollector()
        kalshi_ticker = config.get("kalshi_series_ticker")
        
        if kalshi_ticker:
            kalshi_markets = kalshi_collector.fetch_markets(series_ticker=kalshi_ticker, limit=100)
            save_raw_data(kalshi_markets, f"kalshi_{category}", timestamp)
            all_markets.extend(kalshi_markets)
        else:
            print(f"No Kalshi ticker configured for {category}")

    # Combine and save processed
    save_processed_data(all_markets, timestamp)

if __name__ == "__main__":
    main()
