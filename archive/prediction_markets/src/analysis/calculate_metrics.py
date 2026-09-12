from typing import Any, Dict, List, Optional


def calculate_average_entry(
    orderbook: List[Dict[str, float]], target_size: float
) -> Optional[float]:
    """
    Calculate the average price to buy 'target_size' amount of contracts.

    Args:
         orderbook (List[Dict[str, float]]): List of orders usually [{'price': 0.1, 'size': 10.0}, ...]
         target_size (float): The amount of contracts to buy.

    Returns:
        Optional[float]: Average entry price, or None if insufficient liquidity.
    """
    if not orderbook:
        return None

    filled_size: float = 0.0
    total_cost: float = 0.0

    # Sort by price. For Asks (buying), we want the lowest price first.
    # We assume usage sends pre-sorted or we sort here to be safe.
    # Standard convention: Asks are sorted low to high.
    sorted_book = sorted(orderbook, key=lambda x: float(x["price"]))

    for level in sorted_book:
        price = float(level["price"])
        size = float(level["size"])

        needed = target_size - filled_size
        take = min(needed, size)

        total_cost += take * price
        filled_size += take

        if filled_size >= target_size:
            break

    if filled_size < target_size:
        return None  # Not enough liquidity

    return total_cost / filled_size


def calculate_slippage(
    orderbook: List[Dict[str, float]], best_price: float, target_sizes: List[float]
) -> List[Dict[str, Any]]:
    """
    Calculate slippage for multiple target sizes.

    Args:
        orderbook: List of asks (for buying) or bids (for selling).
        best_price: The best available price (reference point).
        target_sizes: List of sizes to test.

    Returns:
        List[Dict]: List of results with size, avg_price, and slippage %.
    """
    results = []
    for size in target_sizes:
        avg_price = calculate_average_entry(orderbook, size)
        if avg_price:
            slippage = (avg_price - best_price) / best_price * 100
            results.append({"size": size, "avg_price": avg_price, "slippage": slippage})
        else:
            results.append({"size": size, "avg_price": None, "slippage": None})
    return results
