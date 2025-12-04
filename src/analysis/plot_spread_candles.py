import matplotlib.pyplot as plt
import matplotlib.patches as patches
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime
from src.collectors.polymarket import PolymarketCollector
from src.collectors.kalshi import KalshiCollector

def plot_spread_candles():
    print("Fetching Polymarket Data...")
    poly_collector = PolymarketCollector()
    poly_slug = "starladder-budapest-major-2025-winner"
    poly_event = poly_collector.fetch_event_by_slug(poly_slug)
    
    poly_data = {}
    if poly_event:
        for m in poly_event.get('markets', []):
            team = m.get('groupItemTitle', m.get('question'))
            clob_ids = json.loads(m.get('clobTokenIds', '[]')) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
            best_bid = 0.0
            best_ask = 0.0
            
            if clob_ids:
                token_id = clob_ids[0]
                book = poly_collector.fetch_orderbook(token_id)
                if book.get('bids'):
                    best_bid = float(book['bids'][0]['price'])
                if book.get('asks'):
                    best_ask = float(book['asks'][0]['price'])
            
            # If no book, fallback to 0/1 or outcomePrices if needed, but for spread viz we need real book
            if best_ask == 0.0 and m.get('outcomePrices'):
                 # Fallback to mid if we have a price but no book (unlikely for active)
                 try: p = float(json.loads(m.get('outcomePrices'))[0])
                 except: p = 0
                 best_bid = p - 0.01 # Fake tight spread for viz if missing? No, better to show 0.
                 best_ask = p + 0.01
            
            poly_data[team.lower()] = {'bid': best_bid, 'ask': best_ask, 'name': team}

    print("Fetching Kalshi Data...")
    kalshi_collector = KalshiCollector()
    kalshi_series = "KXSTARLADDERBUDAPESTMAJOR"
    kalshi_markets = kalshi_collector.fetch_markets(series_ticker=kalshi_series)
    
    kalshi_data = {}
    for m in kalshi_markets:
        title = m.event_name
        team = title.replace("Will ", "").replace(" win the StarLadder Budapest Major 2025?", "").strip()
        kalshi_data[team.lower()] = {'bid': m.bids[0] if m.bids else 0.0, 'ask': m.asks[0] if m.asks else 0.0, 'name': team}

    print("Matching teams...")
    common_teams = []
    for p_team, p_info in poly_data.items():
        if p_team in kalshi_data:
            common_teams.append((p_team, p_info, kalshi_data[p_team]))
            continue
        for k_team in kalshi_data.keys():
            if p_team in k_team or k_team in p_team:
                common_teams.append((k_team, p_info, kalshi_data[k_team]))
                break
    
    if not common_teams:
        print("No matching teams found.")
        return

    # Sort by average price (descending) to put favorites first
    common_teams.sort(key=lambda x: (x[1]['bid'] + x[2]['bid'])/2, reverse=True)

    # Plotting
    fig, ax = plt.subplots(figsize=(14, 8))
    
    names = [item[1]['name'] for item in common_teams]
    y_pos = np.arange(len(names))
    height = 0.35
    
    for i, (key, p, k) in enumerate(common_teams):
        # Polymarket Bar (Blue)
        # Range from Bid to Ask
        p_width = p['ask'] - p['bid']
        if p_width <= 0: p_width = 0.005 # Min width for visibility
        
        ax.broken_barh([(p['bid'], p_width)], (y_pos[i] - height/2, height), facecolor='#2D9CDB', alpha=0.7, label='Polymarket' if i == 0 else "")
        
        # Kalshi Bar (Green)
        k_width = k['ask'] - k['bid']
        if k_width <= 0: k_width = 0.005
        
        ax.broken_barh([(k['bid'], k_width)], (y_pos[i] + height/2, height), facecolor='#00D1C1', alpha=0.7, label='Kalshi' if i == 0 else "")
        
        # Check for Arbitrage and Highlight
        # Arb 1: Poly Bid > Kalshi Ask
        if p['bid'] > k['ask']:
            gap = p['bid'] - k['ask']
            # Draw a connector or highlight region
            rect = patches.Rectangle((k['ask'], y_pos[i] - height), gap, height*2, linewidth=1, edgecolor='gold', facecolor='gold', alpha=0.3, hatch='///')
            ax.add_patch(rect)
            ax.text(k['ask'] + gap/2, y_pos[i], f"ARB\n{gap:.1%}", ha='center', va='center', fontsize=8, color='darkgoldenrod', fontweight='bold')

        # Arb 2: Kalshi Bid > Poly Ask
        if k['bid'] > p['ask']:
            gap = k['bid'] - p['ask']
            rect = patches.Rectangle((p['ask'], y_pos[i] - height), gap, height*2, linewidth=1, edgecolor='gold', facecolor='gold', alpha=0.3, hatch='///')
            ax.add_patch(rect)
            ax.text(p['ask'] + gap/2, y_pos[i], f"ARB\n{gap:.1%}", ha='center', va='center', fontsize=8, color='darkgoldenrod', fontweight='bold')

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names)
    ax.set_xlabel('Price (Probability)')
    ax.set_title('Bid-Ask Spread & Arbitrage Opportunities (Polymarket vs Kalshi)')
    ax.grid(True, alpha=0.2, axis='x')
    
    # Legend
    handles, labels = ax.get_legend_handles_labels()
    from matplotlib.lines import Line2D
    arb_patch = patches.Patch(facecolor='gold', alpha=0.3, hatch='///', label='Arbitrage Gap')
    handles.append(arb_patch)
    ax.legend(handles=handles, loc='upper right')

    # Timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plt.figtext(0.99, 0.01, f"Generated at: {current_time}", horizontalalignment='right', fontsize=8, color='gray')

    plt.tight_layout()
    os.makedirs("plots/cs2_starladder_budapest_major", exist_ok=True)
    ts_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plots/cs2_starladder_budapest_major/spread_candles_{ts_filename}.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")

if __name__ == "__main__":
    plot_spread_candles()
