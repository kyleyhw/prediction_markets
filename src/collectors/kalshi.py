from typing import Any, Dict, List, Optional

import requests

from .base import BaseCollector, MarketEvent


class KalshiCollector(BaseCollector):
    """
    Collector for Kalshi data using the V2 API.
    """

    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
    # Using public endpoint if available, or standard

    def fetch_markets(
        self, series_ticker: str = "KXCSGOGAME", limit: int = 100, **kwargs: Any
    ) -> List[MarketEvent]:
        """
        Fetch markets from Kalshi.

        Args:
            series_ticker (str): The series ticker to filter by.
            limit (int): Number of markets to fetch.
            **kwargs: Additional arguments.

        Returns:
            List[MarketEvent]: Standardized market events.
        """
        endpoint = f"{self.BASE_URL}/markets"
        params = {"limit": limit, "series_ticker": series_ticker}

        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

            markets: List[MarketEvent] = []
            for market in data.get("markets", []):
                markets.append(self._parse_market(market))
            return markets

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from Kalshi: {e}")
            return []

    def _parse_market(self, market: Dict[str, Any]) -> MarketEvent:
        """
        Parse a single market dictionary into a MarketEvent object.

        Args:
            market (Dict[str, Any]): The market data.

        Returns:
            MarketEvent: The standardized market event.
        """
        # Standardize Prices (Kalshi prices are in cents 1-99)
        best_bid = float(market.get("yes_bid", 0)) / 100.0
        best_ask = float(market.get("yes_ask", 0)) / 100.0
        mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else 0.0
        spread = best_ask - best_bid if (best_bid and best_ask) else 0.0
        last_price = float(market.get("price", 0)) / 100.0

        # Construct Orderbook (Simulated)
        orderbook_data: Dict[str, List[Dict[str, float]]] = {
            "bids": [{"price": best_bid, "size": 0.0}] if best_bid else [],
            "asks": [{"price": best_ask, "size": 0.0}] if best_ask else [],
        }

        start_time = self._parse_date(market.get("open_time"))

        return MarketEvent(
            event_id=str(market.get("ticker", "")),
            event_name=str(market.get("title", "Unknown Event")),
            description=str(market.get("subtitle", "")),
            start_time=start_time,
            outcomes=["Yes", "No"],
            prices=[last_price, 1.0 - last_price],
            volume=float(market.get("volume", 0)),
            liquidity=float(market.get("liquidity", 0)),
            platform="kalshi",
            url=f"https://kalshi.com/markets/{market.get('ticker', '')}",
            bids=[best_bid],  # Legacy
            asks=[best_ask],  # Legacy
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid_price,
            spread=spread,
            last_price=last_price,
            orderbook=orderbook_data,
        )

    def fetch_candlesticks(
        self,
        series_ticker: str,
        market_ticker: str,
        start_ts: int,
        end_ts: Optional[int] = None,
        period_interval: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Fetch candlesticks for a specific market.

        Args:
            series_ticker (str): Series ticker.
            market_ticker (str): Market ticker.
            start_ts (int): Start timestamp.
            end_ts (Optional[int]): End timestamp (defaults to now).
            period_interval (int): Candle size in minutes/seconds? Usually minutes
                                   in v2.

        Returns:
            List[Dict[str, Any]]: List of candlesticks.
        """
        import time

        if end_ts is None:
            end_ts = int(time.time())

        endpoint = (
            f"{self.BASE_URL}/series/{series_ticker}/markets/{market_ticker}/"
            f"candlesticks"
        )
        params = {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": period_interval,
            "limit": 5000,
        }

        try:
            response = requests.get(endpoint, params=params)
            # print(f"Kalshi Status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            return data.get("candlesticks", [])
        except requests.exceptions.RequestException as e:
            print(f"Error fetching candlesticks for {market_ticker}: {e}")
            return []
