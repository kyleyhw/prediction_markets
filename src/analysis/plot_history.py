import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
from src.collectors.polymarket import PolymarketCollector
import os

def plot_market_history(market_id: str, event_name: str = "Market History"):
    collector = PolymarketCollector()
    print(f"Fetching history for market ID: {market_id}...")
    
    # Fetch history (default 1h interval)
    history = collector.fetch_price_history(market_id, interval="1h")
    
    if not history:
        print("No history found.")
        return

    # Convert to DataFrame
    df = pd.DataFrame(history)
    # Expected columns: 't' (timestamp), 'p' (price) or similar
    # Gamma API history format: [{'t': 1234567890, 'p': 0.5}, ...]
    
    if 't' not in df.columns or 'p' not in df.columns:
        print(f"Unexpected data format: {df.columns}")
        return

    df['timestamp'] = pd.to_datetime(df['t'], unit='s')
    df['price'] = df['p']
    
    # Plot
    plt.figure(figsize=(12, 6))
    plt.plot(df['timestamp'], df['price'], label='Price (Probability)', color='blue')
    plt.title(f"Odds Over Time: {event_name}")
    plt.xlabel("Date")
    plt.ylabel("Implied Probability")
    plt.grid(True, alpha=0.3)
    plt.legend()
    
    # Save plot
    os.makedirs("plots", exist_ok=True)
    filename = f"plots/history_{market_id}.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")

if __name__ == "__main__":
    # Dynamic discovery of a valid ID for demo:
    print("Fetching an active market to test history...")
    collector = PolymarketCollector()
    markets = collector.fetch_markets(limit=5)
    
    found = False
    for m in markets:
        # Try to find one with volume
        if m.volume > 1000:
            print(f"Testing with active market: {m.event_name} (ID: {m.event_id})")
            plot_market_history(m.event_id, m.event_name)
            found = True
            break
            
    if not found and markets:
        # Fallback to first one
        m = markets[0]
        print(f"Testing with market: {m.event_name} (ID: {m.event_id})")
        plot_market_history(m.event_id, m.event_name)
    elif not markets:
        print("No markets found to test.")
