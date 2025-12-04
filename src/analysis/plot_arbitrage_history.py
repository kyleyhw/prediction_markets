import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
from src.collectors.polymarket import PolymarketCollector
from src.collectors.kalshi import KalshiCollector

def plot_arbitrage_history():
    print("Initializing Collectors...")
    poly_collector = PolymarketCollector()
    kalshi_collector = KalshiCollector()
    
    # Event Details
    poly_slug = "starladder-budapest-major-2025-winner"
    kalshi_series = "KXSTARLADDERBUDAPESTMAJOR"
    
    print("Fetching Metadata...")
    poly_event = poly_collector.fetch_event_by_slug(poly_slug)
    kalshi_markets = kalshi_collector.fetch_markets(series_ticker=kalshi_series)
    
    if not poly_event or not kalshi_markets:
        print("Failed to fetch event metadata.")
        return

    # Map Teams
    # Poly: market['groupItemTitle'] -> CLOB ID
    # Kalshi: market.event_name -> event_id
    
    poly_map = {}
    for m in poly_event.get('markets', []):
        team = m.get('groupItemTitle', m.get('question')).lower()
        clob_ids = json.loads(m.get('clobTokenIds', '[]')) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
        mid = clob_ids[0] if clob_ids else m.get('id')
        poly_map[team] = mid
        
    kalshi_map = {}
    for m in kalshi_markets:
        title = m.event_name
        team = title.replace("Will ", "").replace(" win the StarLadder Budapest Major 2025?", "").strip().lower()
        kalshi_map[team] = m.event_id
        
    common_teams = set(poly_map.keys()) & set(kalshi_map.keys())
    print(f"Found {len(common_teams)} common teams.")
    
    if not common_teams:
        print("No common teams found.")
        return

    # Fetch History
    start_dt = datetime.now() - timedelta(days=7)
    start_ts = int(start_dt.timestamp())
    
    plt.figure(figsize=(14, 8))
    
    for team in common_teams:
        print(f"Processing {team}...")
        
        # Poly History
        poly_hist = poly_collector.fetch_price_history(poly_map[team], interval="max") # or 1h?
        # Kalshi History
        kalshi_hist = kalshi_collector.fetch_candlesticks(kalshi_series, kalshi_map[team], start_ts=start_ts)
        
        if not poly_hist or not kalshi_hist:
            print(f"  Missing history for {team}")
            continue
            
        # Process Poly
        df_p = pd.DataFrame(poly_hist)
        df_p['t'] = pd.to_datetime(df_p['t'], unit='s')
        df_p = df_p.set_index('t')['p'].astype(float)
        df_p = df_p.resample('1H').mean() # Resample to hourly
        
        # Process Kalshi
        df_k = pd.DataFrame(kalshi_hist)
        df_k['t'] = pd.to_datetime(df_k['end_period_ts'], unit='s')
        
        def get_k_price(row):
            p = row.get('price', {})
            if p and p.get('close') is not None:
                return float(p['close']) / 100.0
            ask = row.get('yes_ask', {}).get('close')
            bid = row.get('yes_bid', {}).get('close')
            if ask is not None and bid is not None:
                return (float(ask) + float(bid)) / 200.0
            elif ask is not None:
                return float(ask) / 100.0
            return 0.0
            
        df_k['price'] = df_k.apply(get_k_price, axis=1)
        df_k = df_k.set_index('t')['price']
        df_k = df_k.resample('1H').mean()
        
        # Align
        aligned = pd.concat([df_p, df_k], axis=1, keys=['poly', 'kalshi']).dropna()
        
        if aligned.empty:
            print(f"  No overlapping data for {team}")
            continue
            
        # Calculate Spread (Poly - Kalshi)
        aligned['diff'] = aligned['poly'] - aligned['kalshi']
        
        # Plot only if significant diff or just plot all?
        # Let's plot all lines
        plt.plot(aligned.index, aligned['diff'], label=f"{team}")
        
    plt.axhline(0, color='black', linewidth=0.8, linestyle='--')
    plt.title("Arbitrage Opportunity Over Time (Polymarket - Kalshi)")
    plt.xlabel("Date")
    plt.ylabel("Price Difference (Probability)")
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, alpha=0.3)
    
    # Add timestamp to plot
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plt.figtext(0.99, 0.01, f"Generated at: {current_time}", horizontalalignment='right', fontsize=8, color='gray')
    
    plt.tight_layout()
    
    os.makedirs("plots/cs2_starladder_budapest_major", exist_ok=True)
    
    # Timestamped filename
    ts_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plots/cs2_starladder_budapest_major/arbitrage_history_{ts_filename}.png"
    plt.savefig(filename)
    print(f"Saved plot to {filename}")

if __name__ == "__main__":
    plot_arbitrage_history()
