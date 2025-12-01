import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime
from src.collectors.polymarket import PolymarketCollector
from src.collectors.kalshi import KalshiCollector

def compare_starladder_odds():
    print("Fetching Polymarket Data...")
    poly_collector = PolymarketCollector()
    poly_slug = "starladder-budapest-major-2025-winner"
    poly_event = poly_collector.fetch_event_by_slug(poly_slug)
    
    poly_data = {}
    if poly_event:
        print(f"  Found Polymarket Event: {poly_event.get('title')}")
        for m in poly_event.get('markets', []):
            team = m.get('groupItemTitle', m.get('question'))
            # Price is usually in outcomePrices (list of strings)
            prices = json.loads(m.get('outcomePrices', '[]')) if isinstance(m.get('outcomePrices'), str) else m.get('outcomePrices', [])
            # Assuming index 0 is Yes? Or index 1?
            # Polymarket binary: [0] is usually 'Yes' or 'No'? 
            # Actually outcomePrices usually matches outcomes order.
            # outcomes: ["Yes", "No"] -> prices: [0.2, 0.8]
            # Let's assume index 0 is the primary outcome (Win).
            # Wait, usually for "Winner" markets, it's "Yes" price we care about.
            # Let's check outcomes.
            outcomes = json.loads(m.get('outcomes', '[]')) if isinstance(m.get('outcomes'), str) else m.get('outcomes', [])
            price = 0.0
            if prices:
                try:
                    price = float(prices[0]) # Taking first price
                except: pass
            
            volume = float(m.get('volume', 0))
            poly_data[team.lower()] = {'price': price, 'volume': volume, 'name': team}

    print("Fetching Kalshi Data...")
    kalshi_collector = KalshiCollector()
    kalshi_series = "KXSTARLADDERBUDAPESTMAJOR"
    kalshi_markets = kalshi_collector.fetch_markets(series_ticker=kalshi_series)
    
    kalshi_data = {}
    print(f"  Found {len(kalshi_markets)} Kalshi markets.")
    for m in kalshi_markets:
        # Title format: "Will Team X win the..."
        # Extract Team Name
        title = m.event_name
        team = title.replace("Will ", "").replace(" win the StarLadder Budapest Major 2025?", "").strip()
        
        # Prices: [Yes, No]
        price = m.prices[0] # Yes price
        volume = m.volume
        kalshi_data[team.lower()] = {'price': price, 'volume': volume, 'name': team}

    # Match and Plot
    print("Matching teams...")
    common_teams = []
    
    # Fuzzy match or direct match
    for k_team, k_info in kalshi_data.items():
        # Simple match
        if k_team in poly_data:
            common_teams.append((k_team, poly_data[k_team], k_info))
        else:
            # Try partial match
            for p_team, p_info in poly_data.items():
                if k_team in p_team or p_team in k_team:
                    common_teams.append((k_team, p_info, k_info)) # Use Kalshi name key but Poly info
                    break
    
    if not common_teams:
        print("No matching teams found.")
        return

    print(f"Found {len(common_teams)} matching teams.")
    
    # Prepare Data for Plotting
    names = [item[2]['name'] for item in common_teams]
    poly_prices = [item[1]['price'] for item in common_teams]
    kalshi_prices = [item[2]['price'] for item in common_teams]
    poly_vols = [item[1]['volume'] for item in common_teams]
    kalshi_vols = [item[2]['volume'] for item in common_teams]
    
    x = np.arange(len(names))
    width = 0.35

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [2, 1]})
    
    # Odds Comparison
    rects1 = ax1.bar(x - width/2, poly_prices, width, label='Polymarket', color='#2D9CDB')
    rects2 = ax1.bar(x + width/2, kalshi_prices, width, label='Kalshi', color='#00D1C1')

    ax1.set_ylabel('Implied Probability')
    ax1.set_title('Starladder Major Winner Odds Comparison')
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=45, ha='right')
    ax1.legend()
    ax1.grid(True, alpha=0.2, axis='y')

    # Label with Volume
    def autolabel(rects, volumes):
        for rect, vol in zip(rects, volumes):
            height = rect.get_height()
            ax1.annotate(f'${int(vol):,}',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=8, rotation=90)

    autolabel(rects1, poly_vols)
    autolabel(rects2, kalshi_vols)

    # Difference Plot
    diffs = np.array(poly_prices) - np.array(kalshi_prices)
    colors = ['#27AE60' if d > 0 else '#E74C3C' for d in diffs] # Green if Poly > Kalshi
    
    ax2.bar(x, diffs, width*1.5, color=colors)
    ax2.axhline(0, color='black', linewidth=0.8)
    ax2.set_ylabel('Difference (Poly - Kalshi)')
    ax2.set_title('Arbitrage / Spread (Positive = Poly Higher)')
    ax2.set_xticks(x)
    ax2.set_xticklabels(names, rotation=45, ha='right')
    ax2.grid(True, alpha=0.2, axis='y')

    # Add timestamp to plot
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plt.figtext(0.99, 0.01, f"Generated at: {current_time}", horizontalalignment='right', fontsize=8, color='gray')

    plt.tight_layout()
    os.makedirs("plots/cs2_starladder_budapest_major", exist_ok=True)
    
    # Timestamped filename
    ts_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plots/cs2_starladder_budapest_major/starladder_odds_comparison_{ts_filename}.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")

if __name__ == "__main__":
    compare_starladder_odds()
