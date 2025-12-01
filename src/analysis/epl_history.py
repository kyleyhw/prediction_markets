import matplotlib.pyplot as plt
import pandas as pd
import os
from src.collectors.polymarket import PolymarketCollector
import time

def analyze_epl_history():
    collector = PolymarketCollector()
    print("Searching for closed EPL markets (Tag 306)...")
    
    # Fetch closed markets for EPL (Tag 306)
    # Limit 50 to get a good sample from last season
    events = collector.fetch_markets(tag_id="306", limit=50, closed=True)
    
    print(f"Found {len(events)} closed EPL events.")
    
    os.makedirs("plots/epl_history", exist_ok=True)
    
    count = 0
    for event in events:
        # Filter for Match Winner markets usually titled "Premier League: Team A vs Team B"
        # or similar. We want to avoid "Winner 2023/24" futures if possible, or maybe that's what we want?
        # The user said "EPL games", so matches.
        
        if "vs" not in event.event_name and " - " not in event.event_name:
            continue
            
        print(f"Processing: {event.event_name} (ID: {event.event_id})")
        
        # Fetch history
        # interval="max" gives the full history with auto-resolution
        history = collector.fetch_price_history(event.event_id, interval="max")
        
        if not history:
            print("  No history found.")
            continue
            
        df = pd.DataFrame(history)
        if 't' not in df.columns or 'p' not in df.columns:
            continue
            
        df['timestamp'] = pd.to_datetime(df['t'], unit='s')
        df['price'] = df['p']
        
        # Plot
        plt.figure(figsize=(10, 6))
        plt.plot(df['timestamp'], df['price'], label='Implied Probability', color='#00ff87') # EPL Green-ish
        plt.title(f"Odds History: {event.event_name}")
        plt.xlabel("Date")
        plt.ylabel("Probability")
        plt.ylim(0, 1)
        plt.grid(True, alpha=0.3)
        plt.legend()
        
        # Sanitize filename
        safe_name = "".join([c for c in event.event_name if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
        filename = f"plots/epl_history/{safe_name}.png"
        plt.savefig(filename)
        plt.close()
        print(f"  Saved plot to {filename}")
        
        count += 1
        if count >= 5: # Limit to 5 plots for now to verify
            break

if __name__ == "__main__":
    analyze_epl_history()
