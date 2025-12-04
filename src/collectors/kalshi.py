import requests
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseCollector, MarketEvent

class KalshiCollector(BaseCollector):
    """
    Collector for Kalshi data using the V2 API.
    """
    
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2" # Using public endpoint if available, or standard

    def fetch_markets(self, series_ticker: str = 'KXCSGOGAME', limit: int = 100) -> List[MarketEvent]:
        """
        Fetch markets from Kalshi.
        
        Args:
            series_ticker (str): The series ticker to filter by (default: 'KXCSGOGAME' for CS:GO/CS2).
            limit (int): Number of markets to fetch.
            
        Returns:
            List[MarketEvent]: Standardized market events.
        """
        endpoint = f"{self.BASE_URL}/markets"
        params = {
            "limit": limit,
            # "status": "open", # Removed to allow 'active' and others
            "series_ticker": series_ticker
        }
        
        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            
            markets = []
            for market in data.get('markets', []):
                markets.append(self._parse_market(market))
            return markets
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from Kalshi: {e}")
            return []

    def _parse_market(self, market: Dict[str, Any]) -> MarketEvent:
        """
        Parse a single market dictionary into a MarketEvent object.
        """
        # Kalshi structure is different. Usually 'yes_bid', 'yes_ask', etc.
        # We need to normalize to a list of outcomes and prices.
        # For binary markets, outcomes are usually Yes/No.
        
        outcomes = ["Yes", "No"]
        
        # Price is usually in cents (1-99), we convert to 0.0-1.0
        yes_bid = float(market.get('yes_bid', 0)) / 100.0
        yes_ask = float(market.get('yes_ask', 0)) / 100.0
        no_bid = float(market.get('no_bid', 0)) / 100.0
        no_ask = float(market.get('no_ask', 0)) / 100.0
        
        # Prices list (using best bid as current price proxy, or mid)
        # User wants bid/ask, so let's store them explicitly
        prices = [yes_bid, no_bid]
        bids = [yes_bid, no_bid]
        asks = [yes_ask, no_ask]

        return MarketEvent(
            event_name=market.get('title', 'Unknown Event'),
            event_id=market.get('ticker'),
            description=market.get('subtitle', ''),
            start_time=self._parse_date(market.get('open_time')),
            outcomes=outcomes,
            prices=prices,
            bids=bids,
            asks=asks,
            volume=float(market.get('volume', 0)),
            liquidity=float(market.get('liquidity', 0)), # Kalshi might not expose liquidity directly in this endpoint
            platform='kalshi',
            url=f"https://kalshi.com/markets/{market.get('ticker')}"
        )

    def _parse_date(self, date_str: str) -> datetime:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            return None
    def fetch_candlesticks(self, series_ticker: str, market_ticker: str, start_ts: int, end_ts: int = None, period_interval: int = 60) -> List[Dict]:
        """
        Fetch candlesticks for a specific market.
        """
        import time
        if end_ts is None:
            end_ts = int(time.time())
            
        # Endpoint: /series/{series_ticker}/markets/{market_ticker}/candlesticks
        endpoint = f"{self.BASE_URL}/series/{series_ticker}/markets/{market_ticker}/candlesticks"
        params = {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": period_interval,
            "limit": 5000 # Max limit
        }
        
        try:
            response = requests.get(endpoint, params=params)
            if response.status_code != 200:
                print(f"Kalshi Error ({response.status_code}): {response.text}")
            response.raise_for_status()
            data = response.json()
            return data.get('candlesticks', [])
        except requests.exceptions.RequestException as e:
            print(f"Error fetching candlesticks for {market_ticker}: {e}")
            return []
