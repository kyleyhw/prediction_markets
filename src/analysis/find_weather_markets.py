from src.collectors.polymarket import PolymarketCollector


def main():
    collector = PolymarketCollector()

    # 1. Fetch ALL active markets (lightweight, no CLOB)
    print("Fetching all active markets...")
    markets = collector.fetch_all_active_markets(fetch_book=False)

    # 2. Filter for Weather
    keywords = [
        "Weather",
        "Climate",
        "Temperature",
        "Hurricane",
        "Rain",
        "Snow",
        "Degree",
    ]
    valid_tags = ["Weather", "Climate", "Science"]

    matches = []
    for m in markets:
        # Check title
        title_lower = m.event_name.lower()
        is_weather = any(k.lower() in title_lower for k in keywords)

        # Check tags
        if not is_weather and m.tags:
            is_weather = any(t in valid_tags for t in m.tags)

        if is_weather:
            matches.append(m)

    print(f"\nFound {len(matches)} Weather related markets.")

    # 3. Sort by Volume
    matches.sort(key=lambda x: x.volume, reverse=True)

    # 4. Display Results
    print(f"\n{'Event':<60} | {'Volume':<12} | {'Liquidity':<12} | {'End Date':<12}")
    print("-" * 110)

    for m in matches:
        date_str = m.end_date.strftime("%Y-%m-%d") if m.end_date else "N/A"
        print(
            f"{m.event_name[:58]:<60} | ${m.volume:,.0f}     | ${m.liquidity:,.0f}     | {date_str}"
        )


if __name__ == "__main__":
    main()
