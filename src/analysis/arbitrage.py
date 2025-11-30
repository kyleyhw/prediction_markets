import pandas as pd
import json
import os
import matplotlib.pyplot as plt
from src.utils.matching import match_events

DATA_DIR = "data/processed"

def load_latest_data():
    files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    if not files:
        print("No data found.")
        return None
    latest_file = sorted(files)[-1]
    print(f"Loading data from {latest_file}")
    return pd.read_csv(os.path.join(DATA_DIR, latest_file))

def parse_prices(prices_str):
    try:
        return json.loads(prices_str)
    except:
        return []

def analyze_arbitrage():
    df = load_latest_data()
    if df is None:
        return

    # Separate by platform
    poly_df = df[df['platform'] == 'polymarket'].copy()
    kalshi_df = df[df['platform'] == 'kalshi'].copy()
    
    print(f"Polymarket events: {len(poly_df)}")
    print(f"Kalshi events: {len(kalshi_df)}")
    
    # Convert to list of dicts for matching
    poly_events = poly_df.to_dict('records')
    kalshi_events = kalshi_df.to_dict('records')
    
    # Match events
    matches = match_events(poly_events, kalshi_events, threshold=0.5) # Lower threshold for testing
    print(f"Found {len(matches)} potential matches.")
    
    for poly, kalshi, score in matches:
        print(f"\nMatch (Score: {score:.2f}):")
        print(f"Poly: {poly['event_name']}")
        print(f"Kalshi: {kalshi['event_name']}")
        
        # Parse prices
        p_prices = parse_prices(poly['prices'])
        k_prices = parse_prices(kalshi['prices'])
        
        if not p_prices or not k_prices:
            continue
            
        # Assuming binary Yes/No for simplicity
        # Polymarket: [Yes, No] (usually)
        # Kalshi: [Yes, No] (as standardized)
        
        poly_yes = p_prices[0]
        kalshi_yes = k_prices[0]
        
        print(f"Poly Yes: {poly_yes:.2f}, Kalshi Yes: {kalshi_yes:.2f}")
        diff = abs(poly_yes - kalshi_yes)
        print(f"Difference: {diff:.2f}")
        
        # Simple Arbitrage Check
        # Buy Yes on A, Buy No on B? 
        # Or just price diff.
        # If Poly Yes = 0.6, Kalshi Yes = 0.5.
        # Buy Yes on Kalshi (0.5), Sell Yes on Poly (0.6) -> Profit 0.1 (ignoring fees/spread)
        
        if diff > 0.05:
            print(">> Significant Discrepancy Found!")

if __name__ == "__main__":
    analyze_arbitrage()
