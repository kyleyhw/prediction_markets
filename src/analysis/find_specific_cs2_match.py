import requests


def find_specific_match():
    # Fetch a large number of events to ensure we cover the timeline
    url = "https://gamma-api.polymarket.com/events"
    params = {"limit": 1000, "closed": "false"}

    print("Fetching 1000 events to search for 'Spirit' vs 'Falcons'...")
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        found = False

        for event in data:
            title = event.get("title", "").lower()
            # desc = event.get("description", "").lower()

            # Check Event Title
            match_found = False
            if "spirit" in title or "falcons" in title or "vitality" in title:
                match_found = True

            # Check Markets Questions and Outcomes
            if not match_found:
                markets = event.get("markets", [])
                for m in markets:
                    q = m.get("question", "").lower()
                    outcomes = str(m.get("outcomes", "")).lower()
                    if any(
                        x in q or x in outcomes
                        for x in [
                            "spirit",
                            "falcons",
                            "vitality",
                            "navi",
                            "mouz",
                            "themongolz",
                            "faze",
                        ]
                    ):
                        match_found = True
                        break

            if match_found:
                print("\n!!! FOUND MATCH !!!")
                print(f"Title: {event.get('title')}")
                print(f"Slug: {event.get('slug')}")
                print(f"Tags: {event.get('tags')}")
                # Print specific markets that matched
                for m in event.get("markets", []):
                    q = m.get("question", "").lower()
                    if "spirit" in q or "falcons" in q or "vitality" in q:
                        print(f"  Market: {m.get('question')}")
                found = True

        if not found:
            print(
                "Still nothing. Printing ALL tags from Sports/Gaming events "
                "to see structure."
            )
            for event in data:
                # Basic heuristic to find gaming events
                title = event.get("title", "").lower()
                if "game" in title or "sport" in title or "esport" in title:
                    print(f"Event: {event.get('title')} | Tags: {event.get('tags')}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    find_specific_match()
