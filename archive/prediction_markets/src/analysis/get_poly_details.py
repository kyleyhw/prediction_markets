def get_poly_details() -> None:
    import requests

    # ID found earlier
    event_id: str = (
        "52967440738572652056787562218093189505630977773921487444445250710949623968082"
    )
    url: str = f"https://gamma-api.polymarket.com/events/{event_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        event = response.json()
        print(f"Event: {event.get('title')}")
        print(f"Markets: {len(event.get('markets', []))}")
        for m in event.get("markets", []):
            print(
                f"  Market: {m.get('groupItemTitle', m.get('question'))} "
                f"(ID: {m.get('id')})"
            )
            # Also print CLOB Token ID
            clobs = m.get("clobTokenIds", [""])
            if clobs:
                print(f"    CLOB ID: {clobs[0]}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    get_poly_details()
