import pandas as pd
import os
import matplotlib.pyplot as plt

DATA_DIR = "data/processed"

def load_latest_data():
    files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    if not files:
        return None
    latest_file = sorted(files)[-1]
    return pd.read_csv(os.path.join(DATA_DIR, latest_file))

def visualize_dashboard():
    df = load_latest_data()
    if df is None:
        print("No data to visualize.")
        return

    # Create a figure with 2x2 subplots
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Prediction Markets Data Overview', fontsize=16)

    # 1. Market Counts
    counts = df['platform'].value_counts()
    counts.plot(kind='bar', ax=axes[0, 0], color=['#1f77b4', '#ff7f0e'])
    axes[0, 0].set_title('Number of Markets Fetched')
    axes[0, 0].set_ylabel('Count')

    # 2. Volume Distribution (Log Scale)
    # Filter out zero volume for log plot
    df_vol = df[df['volume'] > 0]
    if not df_vol.empty:
        for platform in df['platform'].unique():
            subset = df_vol[df_vol['platform'] == platform]
            axes[0, 1].hist(subset['volume'], bins=30, alpha=0.5, label=platform, log=True)
        axes[0, 1].set_title('Volume Distribution (Log Scale)')
        axes[0, 1].set_xlabel('Volume (USD/Contracts)')
        axes[0, 1].legend()
    else:
        axes[0, 1].text(0.5, 0.5, 'No Volume Data', ha='center')

    # 3. Liquidity Distribution (Log Scale)
    df_liq = df[df['liquidity'] > 0]
    if not df_liq.empty:
        for platform in df['platform'].unique():
            subset = df_liq[df_liq['platform'] == platform]
            axes[1, 0].hist(subset['liquidity'], bins=30, alpha=0.5, label=platform, log=True)
        axes[1, 0].set_title('Liquidity Distribution (Log Scale)')
        axes[1, 0].set_xlabel('Liquidity')
        axes[1, 0].legend()
    else:
        axes[1, 0].text(0.5, 0.5, 'No Liquidity Data', ha='center')

    # 4. Kalshi Market Efficiency (Implied Spread)
    # Spread approx = 1 - (Yes_Bid + No_Bid)
    # Only for Kalshi where we have [Yes_Bid, No_Bid] in 'prices'
    kalshi_df = df[df['platform'] == 'kalshi'].copy()
    if not kalshi_df.empty:
        # Parse prices string to list
        import json
        kalshi_df['prices_list'] = kalshi_df['prices'].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
        # Calculate sum of bids
        kalshi_df['bid_sum'] = kalshi_df['prices_list'].apply(lambda x: sum(x) if isinstance(x, list) and len(x)==2 else 0)
        # Spread = 1.0 - Bid_Sum
        kalshi_df['implied_spread'] = 1.0 - kalshi_df['bid_sum']
        
        # Filter valid spreads (0 to 1)
        valid_spreads = kalshi_df[(kalshi_df['implied_spread'] >= 0) & (kalshi_df['implied_spread'] <= 1)]
        
        axes[1, 1].hist(valid_spreads['implied_spread'], bins=20, color='green', alpha=0.7)
        axes[1, 1].set_title('Kalshi Market Tightness (Implied Spread)')
        axes[1, 1].set_xlabel('Spread (1 - Bid_Sum)')
    else:
        axes[1, 1].text(0.5, 0.5, 'No Kalshi Data for Spreads', ha='center')

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    output_path = "market_dashboard.png"
    plt.savefig(output_path)
    print(f"Saved dashboard to {output_path}")

if __name__ == "__main__":
    visualize_dashboard()
