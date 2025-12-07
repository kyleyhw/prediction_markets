import sys
from typing import Any, Dict, List

import requests


def find_tags_by_keyword(keyword: str, limit_events: int = 50) -> Dict[str, str]:
    """
    Scans recent Polymarket events to find tags matching a keyword.

    Args:
        keyword (str): The keyword to search for in tag labels (case-insensitive).
        limit_events (int): Number of events to scan. Defaults to 50.

    Returns:
        Dict[str, str]: A dictionary of {TagID: TagLabel} for matches.
    """
    url = f"https://gamma-api.polymarket.com/events?limit={limit_events}"
    seen_tags: Dict[str, str] = {}

    try:
        response = requests.get(url)
        response.raise_for_status()
        data: List[Dict[str, Any]] = response.json()

        print(f"Scanning {len(data)} events for tags matching '{keyword}'...")

        for event in data:
            tags: List[Dict[str, Any]] = event.get("tags", [])
            for tag in tags:
                if isinstance(tag, dict) and "id" in tag and "label" in tag:
                    t_id = str(tag["id"])
                    t_label = str(tag["label"])

                    if keyword.lower() in t_label.lower():
                        seen_tags[t_id] = t_label

        return seen_tags

    except requests.RequestException as e:
        print(f"Error scanning tags: {e}", file=sys.stderr)
        return {}


def main() -> None:
    """
    Main entry point for tag search.
    """
    if len(sys.argv) < 2:
        print("Usage: python find_poly_tag.py <keyword>")
        return

    keyword = sys.argv[1]
    matches = find_tags_by_keyword(keyword)

    if matches:
        print(f"\nFound {len(matches)} tags matching '{keyword}':")
        for t_id, t_lbl in matches.items():
            print(f"ID: {t_id:<10} Label: {t_lbl}")
    else:
        print(f"\nNo tags found matching '{keyword}' in the scanned events.")


if __name__ == "__main__":
    main()
