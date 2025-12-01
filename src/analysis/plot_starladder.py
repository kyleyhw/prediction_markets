import matplotlib.pyplot as plt
import pandas as pd
import os
import json
from src.collectors.polymarket import PolymarketCollector

def plot_starladder_odds():
    slug = "starladder-budapest-major-2025-winner"
    collector = PolymarketCollector()
    
    print(f"Fetching event: {slug}...")
    event = collector.fetch_event_by_slug(slug)
    
    if not event:
        print("Event not found.")
        return

    print(f"Found Event: {event.get('title')}")
    
    # This event likely has multiple markets (one per team) or one market with multiple outcomes?
    # Usually "Winner" events are one market with multiple outcomes (Yes/No for each team is separate markets? 
    # Or one market with many outcomes? Polymarket usually does separate binary markets for each team in a "Group" event).
    
    markets = event.get('markets', [])
    print(f"Found {len(markets)} markets (teams/outcomes).")
    
    os.makedirs("plots/cs2_starladder_budapest_major", exist_ok=True)
    
    # We want to plot the "Yes" price for each team over time.
    # Let's collect history for all of them.
    
    plt.figure(figsize=(12, 8))
    
    plotted_count = 0
    for m in markets:
        team_name = m.get('groupItemTitle', m.get('question'))
        print(f"Processing: {team_name}")
        
        # Get CLOB ID
        clob_ids = json.loads(m.get('clobTokenIds', '[]')) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
        mid = clob_ids[0] if clob_ids else m.get('id')
        
        # Fetch history
        # Use "max" or "1h" depending on how long it's been running.
        history = collector.fetch_price_history(mid, interval="max")
        
        if not history:
            print(f"  No history for {team_name}")
            continue
            
        df = pd.DataFrame(history)
        if 't' not in df.columns or 'p' not in df.columns:
            continue
            
        df['timestamp'] = pd.to_datetime(df['t'], unit='s')
        df['price'] = df['p']
        
        # Filter out very low prob teams to keep chart readable?
        # Or just plot top 10.
        current_price = df['price'].iloc[-1]
        if current_price < 0.01: # Skip < 1% chance
            continue
            
        plt.plot(df['timestamp'], df['price'], label=f"{team_name} ({current_price:.2f})")
        plotted_count += 1
        
    if plotted_count == 0:
        print("No significant data to plot.")
        return

    plt.title(f"Odds History: {event.get('title')}")
    plt.xlabel("Date")
    plt.ylabel("Implied Probability")
    plt.ylim(0, 1)
    plt.grid(True, alpha=0.3)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    
    filename = "plots/cs2_starladder_budapest_major/winner_odds.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")

if __name__ == "__main__":
    plot_starladder_odds()
