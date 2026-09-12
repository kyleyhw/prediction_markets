import requests


def try_slugs():
    slugs = [
        "counter-strike-2",
        "cs2",
        "cs-2",
        "counter-strike",
        "csgo",
        "esports",
        "gaming",
        "video-games",
    ]

    url = "https://gamma-api.polymarket.com/events"

    for slug in slugs:
        params = {"tag_slug": slug, "limit": 5}
        try:
            print(f"Testing slug: '{slug}'...")
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data:
                print(f"  SUCCESS! Found {len(data)} events for slug '{slug}'.")
                print(f"  First Event: {data[0].get('title')}")
            else:
                print(f"  No events found for slug '{slug}'.")

        except Exception as e:
            print(f"  Error for slug '{slug}': {e}")


if __name__ == "__main__":
    try_slugs()
