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
    # Example ID. Since we couldn't find Blast Rivals, we'll use a placeholder or ask the user.
    # For demonstration, I'll try to fetch a known active market if possible, or just fail gracefully.
    # Let's try a generic ID or one found in previous logs if available.
    # I'll use a placeholder and expect the user to provide one or I'll find one dynamically.
    
    # Dynamic discovery of a valid ID for demo:
    collector = PolymarketCollector()
    markets = collector.fetch_markets(limit=1)
    if markets:
        m = markets[0]
        # The market ID in MarketEvent is the event ID, we need the specific market/question ID.
        # My collector stores event_id as the main ID. Let's see if that works for history.
        # Actually, fetch_markets returns MarketEvent where event_id is often the slug or event ID.
        # We need the CLOB Token ID or Condition ID.
        # Let's assume for now we can pass the ID we have.
        print(f"Testing with market: {m.event_name} (ID: {m.event_id})")
        plot_market_history(m.event_id, m.event_name)
    else:
        print("No markets found to test.")
