from src.collectors.polymarket import PolymarketCollector


def main():
    collector = PolymarketCollector()

    # 1. Fetch ALL active markets (lightweight, no CLOB)
    print("Fetching all active markets...")
    markets = collector.fetch_all_active_markets(fetch_book=False)

    # 2. Filter for CS2
    keywords = ["CS2", "Counter Stike", "Counter-Strike", "Major", "IEM", "ESL"]
    valid_tags = ["CS2", "Esports", "Counter Strike"]

    matches = []
    for m in markets:
        # Check title
        title_lower = m.event_name.lower()
        is_cs2 = any(k.lower() in title_lower for k in keywords)

        # Check tags
        if not is_cs2 and m.tags:
            is_cs2 = any(t in valid_tags for t in m.tags)

        if is_cs2:
            matches.append(m)

    print(f"\nFound {len(matches)} CS2 related markets.")

    # 3. Sort by Volume
    matches.sort(key=lambda x: x.volume, reverse=True)

    # 4. Display Results
    print(f"\n{'Event':<60} | {'Volume':<12} | {'Liquidity':<12} | {'Active?':<8}")
    print("-" * 100)

    for m in matches:
        print(
            f"{m.event_name[:58]:<60} | ${m.volume:,.0f} | ${m.liquidity:,.0f} | {m.end_date}"
        )


if __name__ == "__main__":
    main()
