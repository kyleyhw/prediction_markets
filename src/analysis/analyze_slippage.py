import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import List, Dict
from src.collectors.polymarket import PolymarketCollector
from src.collectors.kalshi import KalshiCollector

def calculate_average_entry(orderbook: List[Dict], target_size: float) -> float:
    """
    Calculate the average price to buy 'target_size' amount of contracts.
    """
    if not orderbook:
        return None
    
    filled_size = 0.0
    total_cost = 0.0
    
    # Sort by price (best price first). For Bids (selling), high to low. For Asks (buying), low to high.
    # Assuming this function is called with the correct side (e.g. Asks for buying) sorted correctly.
    # But wait, standard orderbook usually has asks sorted low->high.
    
    for level in orderbook:
        price = level['price']
        size = level['size']
        
        needed = target_size - filled_size
        take = min(needed, size)
        
        total_cost += take * price
        filled_size += take
        
        if filled_size >= target_size:
            break
            
    if filled_size < target_size:
        return None # Not enough liquidity
        
    return total_cost / filled_size

def analyze_slippage():
    # 1. Fetch Data
    print("Fetching Starladder Data...")
    
    # Polymarket
    poly = PolymarketCollector()
    p_event_raw = poly.fetch_event_by_slug("starladder-budapest-major-2025-winner")
    if not p_event_raw:
        print("Polymarket event not found.")
        return
    p_market = poly._parse_market(p_event_raw['markets'][0])
    
    # Kalshi
    kalshi = KalshiCollector()
    k_markets = kalshi.fetch_markets(series_ticker="KXSTARLADDERBUDAPESTMAJOR")
    if not k_markets:
        print("Kalshi event not found.")
        return
    k_market = k_markets[0] # Assuming first is the main one or we match properly
    
    # 2. Define Bet Sizes
    bet_sizes = [100, 500, 1000, 5000, 10000]
    results = []
    
    # 3. Calculate Slippage for Polymarket (Yes Outcome -> Buy from Asks)
    print("Calculating Polymarket Slippage...")
    p_asks = sorted(p_market.orderbook['asks'], key=lambda x: x['price']) # Low to High
    for size in bet_sizes:
        avg_price = calculate_average_entry(p_asks, size)
        if avg_price:
            slippage = (avg_price - p_market.best_ask) / p_market.best_ask * 100
            results.append({
                'Platform': 'Polymarket',
                'Bet Size ($)': size,
                'Avg Entry Price': avg_price,
                'Slippage (%)': slippage
            })

    # 4. Calculate Slippage for Kalshi (Yes Outcome -> Buy from Asks)
    # Note: Kalshi API summary doesn't give full depth, so this is likely just the top of book 
    # unless we had a better source. We will simulate with what we have (flat slippage if depth unknown)
    # or skip if depth is insufficient.
    print("Calculating Kalshi Slippage (Limited Depth)...")
    k_asks = sorted(k_market.orderbook['asks'], key=lambda x: x['price'])
    for size in bet_sizes:
        avg_price = calculate_average_entry(k_asks, size)
        if avg_price:
            slippage = (avg_price - k_market.best_ask) / k_market.best_ask * 100
            results.append({
                'Platform': 'Kalshi',
                'Bet Size ($)': size,
                'Avg Entry Price': avg_price,
                'Slippage (%)': slippage
            })
        else:
             results.append({
                'Platform': 'Kalshi',
                'Bet Size ($)': size,
                'Avg Entry Price': None,
                'Slippage (%)': None
            })

    # 5. Visualize
    df = pd.DataFrame(results)
    print(df)
    
    if not df.empty:
        plt.figure(figsize=(10, 6))
        sns.barplot(data=df, x='Bet Size ($)', y='Slippage (%)', hue='Platform')
        plt.title('Market Slippage Analysis: Cost to Buy "Yes"')
        plt.ylabel('Slippage (%) (Price Impact)')
        plt.xlabel('Bet Size ($)')
        plt.grid(True, alpha=0.3)
        plt.savefig('plots/slippage_analysis.png')
        print("Saved plot to plots/slippage_analysis.png")

if __name__ == "__main__":
    analyze_slippage()
