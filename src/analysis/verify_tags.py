import sys
from typing import Any, Dict, List

import requests


def fetch_events_by_tag(tag_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Fetches events from the Polymarket Gamma API filtered by a specific tag ID.

    Args:
        tag_id (str): The numeric ID of the tag to filter by (e.g., '306' for EPL).
        limit (int): The maximum number of events to return. Defaults to 5.

    Returns:
        List[Dict[str, Any]]: A list of event data dictionaries.

    Raises:
        requests.RequestException: If the API request fails.
    """
    url: str = f"https://gamma-api.polymarket.com/events?limit={limit}&tag_id={tag_id}"
    try:
        response: requests.Response = requests.get(url)
        response.raise_for_status()
        data: List[Dict[str, Any]] = response.json()
        return data
    except requests.RequestException as e:
        print(f"Error fetching events for tag {tag_id}: {e}", file=sys.stderr)
        return []


def discover_tags(limit: int = 10) -> Dict[str, str]:
    """
    Fetches recent events to discover active tags and their IDs.

    Args:
        limit (int): The number of recent events to inspect. Defaults to 10.

    Returns:
        Dict[str, str]: A dictionary mapping Tag ID to Tag Label.
    """
    url: str = f"https://gamma-api.polymarket.com/events?limit={limit}"
    seen_tags: Dict[str, str] = {}

    try:
        response: requests.Response = requests.get(url)
        response.raise_for_status()
        data: List[Dict[str, Any]] = response.json()

        for event in data:
            tags: List[Dict[str, Any]] = event.get("tags", [])
            for tag in tags:
                # Type check for safety
                if isinstance(tag, dict) and "id" in tag and "label" in tag:
                    seen_tags[str(tag["id"])] = str(tag["label"])

        return seen_tags
    except requests.RequestException as e:
        print(f"Error discovering tags: {e}", file=sys.stderr)
        return {}


def main() -> None:
    """
    Main function to verify tag filtering and discovery.
    """
    print("--- Verifying Polymarket Tag Filtering ---")

    # 1. Test filtering by a known tag (EPL = 306)
    target_tag_id: str = "306"
    print(f"\nFetching events for Tag ID: {target_tag_id} (EPL)...")

    epl_events: List[Dict[str, Any]] = fetch_events_by_tag(target_tag_id)

    if epl_events:
        print(f"Found {len(epl_events)} events.")
        for event in epl_events:
            title: str = event.get("title", "Unknown Title")
            tags: List[Dict[str, Any]] = event.get("tags", [])
            tag_labels: List[str] = [t.get("label", "N/A") for t in tags]
            print(f"- {title} (Tags: {tag_labels})")
    else:
        print("No events found for EPL tag.")

    # 2. Discover new tags
    print("\n--- Discovering Active Tags ---")
    discovered_tags: Dict[str, str] = discover_tags(limit=20)

    if discovered_tags:
        print(f"Found {len(discovered_tags)} unique tags:")
        # Sort by Label for readability
        for tag_id, label in sorted(discovered_tags.items(), key=lambda item: item[1]):
            print(f"ID: {tag_id:<10} Label: {label}")
    else:
        print("No tags discovered.")


if __name__ == "__main__":
    main()
