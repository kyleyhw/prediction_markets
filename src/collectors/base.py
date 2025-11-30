from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

@dataclass
class MarketEvent:
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

    def to_dict(self):
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
            "url": self.url
        }

class BaseCollector(ABC):
    """
    Abstract base class for prediction market data collectors.
    """

    @abstractmethod
    def fetch_markets(self, **kwargs) -> List[MarketEvent]:
        """
        Fetch markets from the API.
        
        Args:
            **kwargs: Filter parameters (e.g., tags, series_ticker).
            
        Returns:
            List[MarketEvent]: A list of standardized market events.
        """
        pass
