import argparse
from datetime import datetime, timezone
from typing import Optional

from src.collectors.polymarket import PolymarketCollector


def find_markets(
    tag: Optional[str] = None,
    slug: Optional[str] = None,
    min_volume: float = 0,
    min_liquidity: float = 0,
    max_spread: Optional[float] = None,
    limit: int = 100,
    fetch_all: bool = False,
):
    print("Fetching markets...")
    collector = PolymarketCollector()

    # If slug is provided, filter server-side
    kwargs = {}
    if slug:
        kwargs["tag_slug"] = slug

    if fetch_all:
        markets = collector.fetch_all_active_markets(batch_size=500, **kwargs)
    else:
        # Default behavior: fetch one batch
        print(f"Fetching limited batch ({limit})...")
        markets = collector.fetch_markets(limit=limit, **kwargs)

    print(f"Fetched {len(markets)} raw markets.")

    filtered_markets = []

    for m in markets:
        # Filter by Tag (substring match, case insensitive)
        if tag:
            tag_match = False
            for t in m.tags:
                if tag.lower() in str(t).lower():
                    tag_match = True
                    break
            if not tag_match:
                continue

        # Filter by Volume (Total or 24h?)
        # API returns `volume` (total) and we added `volume_24h`.
        # Let's check against `volume_24h` if available, else total.
        # But for 'interesting' maybe 24h is better proxy for current activity.
        # Let's use volume_24h for the filter if it's > 0, else maybe ignore?
        # Actually proper implementation: use the parsed volume_24h.

        if m.volume_24h < min_volume:
            continue

        if m.liquidity < min_liquidity:
            continue

        if max_spread is not None:
            if m.spread > max_spread:
                continue

        # Check if closed
        if m.end_date and m.end_date < datetime.now(timezone.utc):
            # Already filtered by `closed=False` in fetch_markets but good to be safe
            continue

        filtered_markets.append(m)

    # Sort by 24h volume descending
    filtered_markets.sort(key=lambda x: x.volume_24h, reverse=True)

    print(f"\nFound {len(filtered_markets)} interesting markets:\n")

    header = (
        f"{'Event':<50} | {'Price':<6} | {'Spread':<6} | "
        f"{'Vol 24h':<10} | {'Liq':<10} | {'End Date':<12} | {'Tags'}"
    )
    print(header)
    print("-" * len(header))

    for m in filtered_markets[:20]:  # Show top 20
        tags_str = ", ".join(m.tags[:2])  # First 2 tags
        date_str = m.end_date.strftime("%Y-%m-%d") if m.end_date else "?"
        short_name = (
            (m.event_name[:47] + "...") if len(m.event_name) > 47 else m.event_name
        )

        print(
            f"{short_name:<50} | {m.mid_price:.2f}   | {m.spread:.2f}   | ${m.volume_24h:,.0f}    | ${m.liquidity:,.0f}    | {date_str:<12} | {tags_str}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Find interesting markets on Polymarket."
    )
    parser.add_argument(
        "--tag",
        type=str,
        help="Filter by tag/category (e.g. 'Politics', 'Sports') - Client side filter",
    )
    parser.add_argument(
        "--slug",
        type=str,
        help="Filter by tag slug (e.g. 'cs2', 'nfl') - Server side filter",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fetch ALL active markets (paginated) - WARNING: Slow",
    )
    parser.add_argument(
        "--min-vol", type=float, default=1000, help="Minimum 24h volume (default: 1000)"
    )
    parser.add_argument(
        "--min-liq", type=float, default=500, help="Minimum liquidity (default: 500)"
    )
    parser.add_argument(
        "--max-spread", type=float, default=0.10, help="Maximum spread (default: 0.10)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of markets to fetch (if --all not set) (default: 100)",
    )

    args = parser.parse_args()

    find_markets(
        tag=args.tag,
        slug=args.slug,
        min_volume=args.min_vol,
        min_liquidity=args.min_liq,
        max_spread=args.max_spread,
        limit=args.limit,
        fetch_all=args.all,
    )
