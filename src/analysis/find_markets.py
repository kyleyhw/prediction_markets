import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from src.collectors.polymarket import MarketEvent, PolymarketCollector

# Path to the external configuration
CONFIG_PATH = Path(__file__).parent / "market_config.json"


def load_config() -> Dict[str, Dict[str, List[str]]]:
    """Load market configuration from JSON file."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def find_markets(category: str, fetch_book: bool = False) -> List[MarketEvent]:
    """
    Find markets based on a configured category.
    """
    config_data = load_config()

    if category not in config_data:
        raise ValueError(
            f"Category '{category}' not found. Available: {list(config_data.keys())}"
        )

    config = config_data[category]
    keywords = [k.lower() for k in config.get("keywords", [])]
    valid_tags = set(config.get("tags", []))
    exclude_terms = [e.lower() for e in config.get("exclude", [])]

    print(f"DEBUG: Loaded config for {category}")
    print(f"DEBUG: Excludes: {exclude_terms}")

    collector = PolymarketCollector()

    print(f"Fetching all active markets to search for '{category}'...")
    all_markets = collector.fetch_all_active_markets(fetch_book=fetch_book)

    matches: List[MarketEvent] = []

    print(f"Filtering {len(all_markets)} markets using:")
    print(f"  Keywords: {keywords}")
    print(f"  Tags:     {valid_tags}")
    print(f"  Exclude:  {exclude_terms}")

    for m in all_markets:
        title_lower = m.event_name.lower()

        # 0. Check Exclusion First
        if any(exc in title_lower for exc in exclude_terms):
            continue

        # 1. Check Title Keywords
        match_keyword = any(k in title_lower for k in keywords)

        # 2. Check Metadata Tags
        match_tag = False
        if m.tags:
            match_tag = any(t in valid_tags for t in m.tags)

        if match_keyword or match_tag:
            matches.append(m)

    matches.sort(key=lambda x: x.volume, reverse=True)
    return matches


def print_results(
    markets: List[MarketEvent], category: str = "", save_report: bool = False
):
    """Print results and optionally save to a timestamped file."""
    timestamp = datetime.now()
    ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    # File friendly timestamp
    ts_file_str = timestamp.strftime("%Y%m%d_%H%M%S")

    header = f"{'Event':<60} | {'Volume':<12} | {'Liquidity':<12} | {'End Date':<12}"
    separator = "-" * 120

    output_lines = []
    output_lines.append(f"\nSearch Report: {category.upper()}")
    output_lines.append(f"Generated at: {ts_str}")
    output_lines.append(f"Found {len(markets)} matching markets.")
    output_lines.append(separator)
    output_lines.append(header)
    output_lines.append(separator)

    for m in markets:
        date_str = m.end_date.strftime("%Y-%m-%d") if m.end_date else "N/A"
        line = f"{m.event_name[:58]:<60} | ${m.volume:,.0f}     | ${m.liquidity:,.0f}     | {date_str}"
        output_lines.append(line)
    output_lines.append(separator)

    # Print to console
    print("\n".join(output_lines))

    # Save to file if requested
    if save_report:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        filename = reports_dir / f"market_report_{category}_{ts_file_str}.md"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# Market Report: {category.upper()}\n\n")
                f.write(f"> **Generated at**: {ts_str}\n\n")
                f.write(f"**Total Found:** {len(markets)}\n\n")
                f.write("| Event | Volume | Liquidity | End Date |\n")
                f.write("| :--- | :--- | :--- | :--- |\n")
                for m in markets:
                    date_str = m.end_date.strftime("%Y-%m-%d") if m.end_date else "N/A"
                    safe_name = m.event_name.replace("|", "-")
                    f.write(
                        f"| {safe_name} | ${m.volume:,.0f} | ${m.liquidity:,.0f} | {date_str} |\n"
                    )
            print(f"\nReport saved to: {filename}")
        except Exception as e:
            print(f"Error saving report: {e}")


def main():
    parser = argparse.ArgumentParser(description="Find prediction markets by category.")
    parser.add_argument(
        "category", nargs="?", help="The market category to search for."
    )
    parser.add_argument(
        "--book", action="store_true", help="Fetch full orderbook details (slower)"
    )
    parser.add_argument(
        "--report", action="store_true", help="Generate a timestamped markdown report."
    )

    args = parser.parse_args()

    # Load config to check available categories
    try:
        config_data = load_config()
        available_cats = list(config_data.keys())
    except Exception as e:
        print(f"Error loading configuration: {e}")
        sys.exit(1)

    # Interactive mode if no argument provided
    if not args.category:
        print("\nAvailable Categories:")
        for key in available_cats:
            print(f" - {key}")

        selected = input("\nEnter category to search: ").strip().lower()
        if selected not in config_data:
            print(f"Invalid category. Please choose from {available_cats}")
            sys.exit(1)
        args.category = selected
    elif args.category not in config_data:
        print(f"Category '{args.category}' not found. Available: {available_cats}")
        sys.exit(1)

    try:
        results = find_markets(args.category, fetch_book=args.book)
        print_results(results, category=args.category, save_report=args.report)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
