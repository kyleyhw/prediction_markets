from src.collectors.polymarket import PolymarketCollector


def verify_price_source():
    collector = PolymarketCollector()
    # Fetch active markets to get a sample
    print("Fetching active markets...")
    markets = collector.fetch_markets(limit=5, closed=False)

    for m in markets:
        print(f"\nMarket: {m.event_name} (ID: {m.event_id})")
        print(f"  Gamma outcomePrices: {m.prices}")
        print(f"  Gamma Liquidity: ${m.liquidity:,.2f}")

        # Calculate calculated liquidity from full book
        total_book_val = 0.0
        val_within_2_percent = 0.0

        # Bids
        best_bid = m.best_bid
        if m.orderbook and "bids" in m.orderbook:
            for b in m.orderbook["bids"]:
                p = float(b["price"])
                s = float(b["size"])
                val = p * s
                total_book_val += val
                if p >= best_bid * 0.98:
                    val_within_2_percent += val

        # Asks
        best_ask = m.best_ask
        if m.orderbook and "asks" in m.orderbook:
            for a in m.orderbook["asks"]:
                p = float(a["price"])
                s = float(a["size"])
                val = p * s  # Cost to buy is Price * Size
                total_book_val += val
                if p <= best_ask * 1.02:
                    val_within_2_percent += val

        print(f"  Calculated Total Book Value: ${total_book_val:,.2f}")
        print(f"  Calculated 2% Depth: ${val_within_2_percent:,.2f}")

        if abs(m.liquidity - total_book_val) < (m.liquidity * 0.1):
            print("  -> Matches Total Book Value (~10% tolerance)")
        elif abs(m.liquidity - val_within_2_percent) < (m.liquidity * 0.1):
            print("  -> Matches 2% Depth (~10% tolerance)")
        else:
            print("  -> Does not match standard depths. Custom formula.")

        print("-" * 40)


if __name__ == "__main__":
    verify_price_source()
