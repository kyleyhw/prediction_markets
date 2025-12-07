from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MarketEvent:
    """
    Standardized data model representing a market event from any prediction market platform.
    """

    event_name: str
    event_id: str
    description: str
    start_time: Optional[datetime]
    outcomes: List[str]
    prices: List[float]  # Price for each outcome (0.0 to 1.0)
    volume: float
    liquidity: float
    platform: str  # 'polymarket' or 'kalshi'
    url: str
    bids: Optional[List[float]] = None
    asks: Optional[List[float]] = None

    # Standardized Fields
    best_bid: float = 0.0
    best_ask: float = 0.0
    mid_price: float = 0.0
    spread: float = 0.0
    last_price: float = 0.0

    # Full Depth
    # Structure: {'bids': [{'price': 0.5, 'size': 100.0}, ...], 'asks': ...}
    orderbook: Dict[str, List[Dict[str, float]]] = field(
        default_factory=lambda: {"bids": [], "asks": []}
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the MarketEvent to a dictionary for serialization.

        Returns:
            Dict[str, Any]: Dictionary representation of the event.
        """
        return {
            "event_name": self.event_name,
            "event_id": self.event_id,
            "description": self.description,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "outcomes": self.outcomes,
            "prices": self.prices,
            "volume": self.volume,
            "liquidity": self.liquidity,
            "platform": self.platform,
            "url": self.url,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "last_price": self.last_price,
            "spread": self.spread,
        }


class BaseCollector(ABC):
    """
    Abstract base class for prediction market data collectors.
    Enforces a common interface for fetching markets.
    """

    @abstractmethod
    def fetch_markets(self, **kwargs: Any) -> List[MarketEvent]:
        """
        Fetch markets from the API.

        Args:
            **kwargs: Filter parameters (e.g., tags, series_ticker).

        Returns:
            List[MarketEvent]: A list of standardized market events.
        """
        pass

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """
        Helper to parse ISO date strings into datetime objects.

        Args:
            date_str (Optional[str]): The ISO 8601 date string.

        Returns:
            Optional[datetime]: Parsed datetime or None if invalid/empty.
        """
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None
