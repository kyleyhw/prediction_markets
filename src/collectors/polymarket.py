import requests
import json
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseCollector, MarketEvent

class PolymarketCollector(BaseCollector):
    """
    Collector for Polymarket data using the Gamma API.
    """
    
    BASE_URL = "https://gamma-api.polymarket.com"

    def fetch_markets(self, tag_id: str = None, limit: int = 100) -> List[MarketEvent]:
        """
        Fetch markets from Polymarket.
        
        Args:
            tag_id (str): The tag ID to filter by (e.g. for 'Esports' or 'Counter-Strike').
            limit (int): Number of markets to fetch.
            
        Returns:
            List[MarketEvent]: Standardized market events.
        """
        endpoint = f"{self.BASE_URL}/events"
        params = {
            "limit": limit,
            "closed": "false"
        }
        if tag_id:
            params["tag_id"] = tag_id
            
        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            
            markets = []
            for event in data:
                # Polymarket events can have multiple markets, but usually for sports it's one main market or related ones.
                # We iterate through the markets within the event.
                for market in event.get('markets', []):
                    markets.append(self._parse_market(event, market))
            return markets
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from Polymarket: {e}")
            return []

    def _parse_market(self, event: Dict[str, Any], market: Dict[str, Any]) -> MarketEvent:
        """
        Parse a single market dictionary into a MarketEvent object.
        """
        # Extract outcomes and prices
        # Polymarket usually has 'outcomePrices' as a JSON string or list in some endpoints.
        # The Gamma API returns 'outcomePrices' as a list of strings representing float prices.
        
        outcomes = json.loads(market.get('outcomes', '[]')) if isinstance(market.get('outcomes'), str) else market.get('outcomes', [])
        prices = json.loads(market.get('outcomePrices', '[]')) if isinstance(market.get('outcomePrices'), str) else market.get('outcomePrices', [])
        
        # Convert prices to float
        try:
            prices = [float(p) for p in prices]
        except (ValueError, TypeError):
            prices = []

        # Extract CLOB Token ID (preferred for history/trading)
        # Gamma API markets usually have 'clobTokenIds'
        clob_token_ids = json.loads(market.get('clobTokenIds', '[]')) if isinstance(market.get('clobTokenIds'), str) else market.get('clobTokenIds', [])
        # Use the first token ID (usually 'Yes' or the main outcome) as the event_id for history fetching
        market_id = clob_token_ids[0] if clob_token_ids else str(market.get('id'))

        return MarketEvent(
            event_name=event.get('title', 'Unknown Event'),
            event_id=market_id,
            description=event.get('description', ''),
            start_time=self._parse_date(event.get('startDate')),
            outcomes=outcomes,
            prices=prices,
            volume=float(market.get('volume', 0)),
            liquidity=float(market.get('liquidity', 0)),
            platform='polymarket',
            url=f"https://polymarket.com/event/{event.get('slug')}"
        )

    def fetch_price_history(self, market_id: str, start_ts: int = None, end_ts: int = None, interval: str = "1h") -> List[Dict]:
        """
        Fetch historical prices for a specific market using the CLOB API.
        """
        # Endpoint: https://clob.polymarket.com/prices-history
        endpoint = "https://clob.polymarket.com/prices-history"
        params = {
            "market": market_id,
            "interval": interval
        }
        if start_ts:
            params["startTs"] = start_ts
        if end_ts:
            params["endTs"] = end_ts
            
        try:
            print(f"Requesting: {endpoint} with params {params}")
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('history', [])
        except Exception as e:
            print(f"Error fetching history for {market_id}: {e}")
            return []

    def _parse_date(self, date_str: str) -> datetime:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            return None
