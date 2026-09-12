
from src.collectors.polymarket import PolymarketCollector


async def analyze_slippage(market_url: str, size: float = 1000.0) -> None:
    """
    Analyze the slippage for a given market URL and trade size.

    Args:
        market_url (str): The URL of the market (e.g. https://polymarket.com/event/...)
        size (float): The trade size in USD (default 1000.0).
    """
    print(f"Analyzing slippage for size ${size:,.2f} on: {market_url}")

    # Extract slug
    # URL format: .../event/slug or .../market/slug... maybe
    # Let's assume standard event/slug format
    try:
        if "event/" in market_url:
            slug = market_url.split("event/")[-1].split("/")[0].split("?")[0]
        else:
            slug = market_url.strip("/").split("/")[-1]
    except Exception:
        print("Error parsing URL. Please provide full Polymarket URL.")
        return

    collector = PolymarketCollector()
    event = collector.fetch_event_by_slug(slug)

    if not event:
        print("Market/Event not found.")
        return

    print(f"Found Event: {event.get('title')}")

    # We need the CLOB Token ID for the main market
    # Just take the first market in the event for now or try to match?
    # Usually the first market is the primary "Winner" one.

    markets = event.get("markets", [])
    if not markets:
        print("No markets found in event.")
        return

    market = markets[0]
    token_id = market.get("clobTokenIds", [])
    if isinstance(token_id, list) and token_id:
        token_id = token_id[0]
    elif isinstance(token_id, str):
        try:
            import json

            token_id = json.loads(token_id)[0]
        except Exception:
            pass

    if not token_id:
        print("No CLOB Token ID found.")
        return

    print(f"Fetching Orderbook for Token: {token_id}")
    book = collector.fetch_orderbook(str(token_id))

    if not book or "asks" not in book:
        print("Empty or invalid orderbook.")
        return

    asks = book["asks"]  # List of {price: '0.99', size: '100'}

    # Sort asks by price ascending
    sorted_asks = sorted(asks, key=lambda x: float(x["price"]))

    total_cost = 0.0
    total_size_acc = 0.0
    filled = False
    avg_price = 0.0

    for level in sorted_asks:
        p = float(level["price"])
        s = float(level["size"])

        remaining_needed = size - total_cost
        cost_at_level = p * s

        if cost_at_level >= remaining_needed:
            # fill remainder here
            # amount of shares we can buy? No, size is in USD.
            # wait, input size is USD "bet size" or "target exposure"?
            # Usually slippage on buy of $X worth of shares?
            # Let's assume size is USD amount TO SPEND.

            # actually usually "Buy $1000 worth" means input $1000.
            total_cost += remaining_needed
            total_size_acc += remaining_needed / p
            filled = True
            break
        else:
            total_cost += cost_at_level
            total_size_acc += s

    if not filled:
        print(f"Warning: Liquidity low for ${size:,.2f}. Book depth exceeded.")

    if total_size_acc > 0:
        avg_price = total_cost / total_size_acc
        best_ask = float(sorted_asks[0]["price"])
        slippage = (avg_price - best_ask) / best_ask * 100

        print("\n--- Results ---")
        print(f"Best Ask:   {best_ask:.4f}")
        print(f"Avg Price:  {avg_price:.4f}")
        print(f"Slippage:   {slippage:.4f}%")
        print(f"Effective Shares: {total_size_acc:,.2f}")
    else:
        print("Calculation failed.")
