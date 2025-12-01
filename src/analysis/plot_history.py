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
    # Example: NBA Mavericks vs Grizzlies
    market_id = "28182404005967940652495463228537840901055649726248190462854914416579180110833"
    event_name = "NBA: Mavericks vs Grizzlies (Dec 4)"
    
    print(f"Plotting history for: {event_name} (ID: {market_id})")
    plot_market_history(market_id, event_name)
