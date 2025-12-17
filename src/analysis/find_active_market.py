import time

from src.collectors.polymarket import PolymarketCollector


def find_active():
    collector = PolymarketCollector()
    print("Fetching markets (limit 300)...")
    markets = collector.fetch_markets(limit=300, closed=False, fetch_book=False)

    # Filter for active topics
    keywords = ["NBA", "NFL"]
    candidates = []

    for m in markets:
        if any(k in m.event_name for k in keywords):
            candidates.append(m)

    print(f"Found {len(candidates)} Sports candidates. Checking spreads for top 50...")

    checked = 0
    for m in candidates:
        if checked >= 50:
            break
        checked += 1
        if not m.clob_token_ids:
            continue

        try:
            # Check Token 0 (usually Yes)
            token_id = str(m.clob_token_ids[0])
            raw_book = collector.fetch_orderbook(token_id)
            bids = raw_book.get("bids", [])
            asks = raw_book.get("asks", [])

            if not bids or not asks:
                continue

            best_bid = float(bids[0]["price"])
            best_ask = float(asks[0]["price"])
            spread = best_ask - best_bid

            # Print ALL details for inspection
            print(f"Market: {m.event_name}")
            print(f"  Liquidity: ${m.liquidity:,.2f}")
            print(f"  Spread: {spread:.4f} (Bid {best_bid}, Ask {best_ask})")

            if spread < 0.1:
                print("  *** ACTIVE FOUND ***")
                # Perform Analysis Here
                mid_price = (best_bid + best_ask) / 2

                # Analyze liquidity correlation
                total_val = sum(
                    float(b["price"]) * float(b["size"]) for b in bids
                ) + sum(float(a["price"]) * float(a["size"]) for a in asks)

                print(f"  Total Book Value: ${total_val:,.2f}")

                ranges = [0.02, 0.05, 0.10, 1.00]
                for r in ranges:
                    min_p = mid_price * (1 - r)
                    max_p = mid_price * (1 + r)
                    val = sum(
                        float(b["price"]) * float(b["size"])
                        for b in bids
                        if float(b["price"]) >= min_p
                    ) + sum(
                        float(a["price"]) * float(a["size"])
                        for a in asks
                        if float(a["price"]) <= max_p
                    )
                    _ = abs(val - m.liquidity)
                    rat = val / m.liquidity if m.liquidity else 0
                    print(f"    Window {r * 100}%: ${val:,.2f} \t(Ratio: {rat:.4f})")

                # Check match
                return

            time.sleep(0.2)

        except Exception:
            continue


if __name__ == "__main__":
    find_active()
