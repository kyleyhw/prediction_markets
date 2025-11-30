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

def visualize_counts():
    df = load_latest_data()
    if df is None:
        print("No data to visualize.")
        return

    counts = df['platform'].value_counts()
    print("Market Counts:")
    print(counts)
    
    plt.figure(figsize=(8, 6))
    counts.plot(kind='bar', color=['blue', 'green'])
    plt.title('Number of Markets Fetched per Platform')
    plt.xlabel('Platform')
    plt.ylabel('Count')
    plt.tight_layout()
    
    output_path = "market_counts.png"
    plt.savefig(output_path)
    print(f"Saved plot to {output_path}")

if __name__ == "__main__":
    visualize_counts()
