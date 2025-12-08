import json
from typing import Any, Dict, List, Optional

import requests

from .base import BaseCollector, MarketEvent


class PolymarketCollector(BaseCollector):
    """
    Collector for Polymarket data using the Gamma API and CLOB API.
    """

    BASE_URL = "https://gamma-api.polymarket.com"

    def fetch_event_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single event by its slug.

        Args:
            slug (str): The event slug strings.

        Returns:
            Optional[Dict[str, Any]]: The event data dictionary or None if not found.
        """
        endpoint = f"{self.BASE_URL}/events"
        params = {"slug": slug}

        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            if not data:
                return None
            return data[0]  # API returns a list
        except requests.exceptions.RequestException as e:
            print(f"Error fetching event {slug}: {e}")
            return None

    def fetch_markets(
        self,
        tag_id: Optional[str] = None,
        limit: int = 100,
        closed: bool = False,
        **kwargs: Any,
    ) -> List[MarketEvent]:
        """
        Fetch markets from Polymarket.

        Args:
            tag_id (Optional[str]): The tag ID to filter by.
            limit (int): Number of markets to fetch.
            closed (bool): Whether to fetch closed markets (default: False).

        Returns:
            List[MarketEvent]: Standardized market events.
        """
        endpoint = f"{self.BASE_URL}/events"
        params = {"limit": limit, "closed": str(closed).lower()}
        if tag_id:
            params["tag_id"] = tag_id

        # Merge additional kwargs into params (e.g. tag_slug)
        params.update(kwargs)

        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

            markets: List[MarketEvent] = []
            for event in data:
                # Polymarket events can have multiple markets.
                for market in event.get("markets", []):
                    parsed_market = self._parse_market(event, market)
                    if parsed_market:
                        markets.append(parsed_market)
            return markets

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from Polymarket: {e}")
            return []

    def fetch_all_active_markets(
        self, batch_size: int = 500, **kwargs: Any
    ) -> List[MarketEvent]:
        """
        Fetch ALL active markets by paginating through the API.

        Args:
            batch_size (int): items per request (default 500).
            **kwargs: Additional filters passed to fetch_markets.

        Returns:
            List[MarketEvent]: Complete list of all active markets.
        """
        all_markets: List[MarketEvent] = []
        offset = 0

        print("Fetching all active markets. This may take a moment...")

        while True:
            # We must force closed=False for "active" markets
            batch = self.fetch_markets(
                limit=batch_size, closed=False, offset=offset, **kwargs
            )

            if not batch:
                break

            all_markets.extend(batch)
            print(
                f"  Fetched batch at offset {offset}, count: {len(batch)} (Total: {len(all_markets)})"
            )

            if len(batch) < batch_size:
                # End of list
                break

            offset += batch_size

        return all_markets

    def _parse_market(
        self, event: Dict[str, Any], market: Dict[str, Any]
    ) -> MarketEvent:
        """
        Parse a single market dictionary into a MarketEvent object.

        Args:
            event (Dict[str, Any]): The parent event data.
            market (Dict[str, Any]): The specific market data.

        Returns:
            MarketEvent: The standardized market event.
        """
        # Extract outcomes and prices
        outcomes: List[str] = (
            json.loads(market.get("outcomes", "[]"))
            if isinstance(market.get("outcomes"), str)
            else market.get("outcomes", [])
        )

        raw_prices = market.get("outcomePrices", [])
        prices: List[float] = []

        if isinstance(raw_prices, str):
            try:
                loaded_prices = json.loads(raw_prices)
                prices = [float(p) for p in loaded_prices]
            except (json.JSONDecodeError, ValueError, TypeError):
                prices = []
        elif isinstance(raw_prices, list):
            try:
                prices = [float(p) for p in raw_prices]
            except (ValueError, TypeError):
                prices = []

        # Fetch Orderbook if CLOB ID exists
        orderbook_data: Dict[str, List[Dict[str, float]]] = {"bids": [], "asks": []}
        best_bid: float = 0.0
        best_ask: float = 0.0

        clob_ids_raw = market.get("clobTokenIds", [])
        clob_ids: List[str] = []

        if isinstance(clob_ids_raw, str):
            try:
                clob_ids = json.loads(clob_ids_raw)
            except json.JSONDecodeError:
                clob_ids = []
        elif isinstance(clob_ids_raw, list):
            clob_ids = clob_ids_raw

        if clob_ids:
            try:
                # Type safe fetch
                raw_book = self.fetch_orderbook(str(clob_ids[0]))

                # Parse Bids
                for b in raw_book.get("bids", []):
                    orderbook_data["bids"].append(
                        {
                            "price": float(b.get("price", 0)),
                            "size": float(b.get("size", 0)),
                        }
                    )
                # Parse Asks
                for a in raw_book.get("asks", []):
                    orderbook_data["asks"].append(
                        {
                            "price": float(a.get("price", 0)),
                            "size": float(a.get("size", 0)),
                        }
                    )

                # Determine Best Bid/Ask safety checks
                if orderbook_data["bids"]:
                    best_bid = float(orderbook_data["bids"][0]["price"])
                if orderbook_data["asks"]:
                    best_ask = float(orderbook_data["asks"][0]["price"])

            except Exception as e:
                # 404 is expected for closed markets or those without a CLOB
                if "404" not in str(e):
                    print(f"Error fetching orderbook for {clob_ids[0]}: {e}")

        # Calculate Derived Metrics
        mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else 0.0
        spread = best_ask - best_bid if (best_bid and best_ask) else 0.0

        last_price = prices[0] if prices else 0.0

        start_time = self._parse_date(event.get("startDate"))

        # Ensure lists are strictly float
        safe_prices: List[float] = [float(p) for p in prices] if prices else [0.0, 0.0]
        if len(safe_prices) < 2:
            safe_prices = [last_price, 1.0 - last_price]

        # Extract Metadata
        tags_raw = event.get("tags", [])
        tags = [t.get("label", t.get("slug")) for t in tags_raw if isinstance(t, dict)]

        end_date = self._parse_date(market.get("endDate"))

        return MarketEvent(
            event_id=str(market.get("id", "")),
            event_name=str(market.get("question", "")),
            description=str(market.get("description", "")),
            start_time=start_time,
            outcomes=outcomes if outcomes else [],
            prices=safe_prices,
            volume=float(market.get("volume", 0)),
            liquidity=float(market.get("liquidity", 0)),
            platform="polymarket",
            url=f"https://polymarket.com/event/{market.get('slug', '')}",
            tags=tags,
            volume_24h=float(market.get("volume24hr", 0)),
            end_date=end_date,
            bids=[best_bid],  # Legacy support
            asks=[best_ask],  # Legacy support
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid_price,
            spread=spread,
            last_price=last_price,
            orderbook=orderbook_data,
        )

    def _get_auth_headers(
        self, method: str, path: str, body: str = ""
    ) -> Dict[str, str]:
        """
        Generate L2 API Key authentication headers.

        Args:
            method (str): HTTP method (GET, POST).
            path (str): API path (e.g. /prices-history).
            body (str): Request body (default: "").

        Returns:
            Dict[str, str]: Headers including Poly-specific auth.
        """
        import base64
        import hashlib
        import hmac
        import time

        from src.config import (
            POLYMARKET_API_KEY,
            POLYMARKET_PASSPHRASE,
            POLYMARKET_SECRET,
        )

        if not all([POLYMARKET_API_KEY, POLYMARKET_SECRET, POLYMARKET_PASSPHRASE]):
            print(
                "Warning: Missing Polymarket API credentials. Authentication will fail."
            )
            return {}

        timestamp = str(int(time.time()))
        message = f"{timestamp}{method}{path}{body}"

        # HMAC-SHA256
        if not POLYMARKET_SECRET:
            return {}

        try:
            secret_bytes = base64.b64decode(POLYMARKET_SECRET)
            signature = hmac.new(
                secret_bytes, message.encode("utf-8"), hashlib.sha256
            ).digest()
            signature_b64 = base64.b64encode(signature).decode("utf-8")

            return {
                "POLY-API-KEY": str(POLYMARKET_API_KEY),
                "POLY-API-SIGNATURE": signature_b64,
                "POLY-TIMESTAMP": timestamp,
                "POLY-PASSPHRASE": str(POLYMARKET_PASSPHRASE),
            }
        except Exception as e:
            print(f"Error generating auth headers: {e}")
            return {}

    def fetch_price_history(
        self,
        market_id: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        interval: str = "1h",
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical prices for a specific market using the CLOB API.

        Args:
            market_id (str): The CLOB market/token ID.
            start_ts (Optional[int]): Start timestamp.
            end_ts (Optional[int]): End timestamp.
            interval (str): Time interval (e.g. '1h').

        Returns:
            List[Dict[str, Any]]: List of history data points.
        """
        base_clob_url = "https://clob.polymarket.com"
        path = "/prices-history"
        endpoint = f"{base_clob_url}{path}"

        params: Dict[str, Any] = {"market": market_id, "interval": interval}
        if start_ts:
            params["startTs"] = start_ts
        if end_ts:
            params["endTs"] = end_ts

        from urllib.parse import urlencode

        query_string = urlencode(params)
        full_path = f"{path}?{query_string}"

        try:
            headers = self._get_auth_headers("GET", full_path)

            # print(f"Requesting CLOB: {endpoint} with params {params}")
            response = requests.get(endpoint, params=params, headers=headers)

            if response.status_code == 401:
                pass  # print(f"Auth Failed: {response.text}")

            response.raise_for_status()
            data = response.json()
            history = data.get("history", [])

            if not history:
                raise ValueError("Empty history from CLOB")

            return history

        except Exception:
            # print(f"CLOB History failed: {e}. Trying Gamma API...")
            # Fallback to Gamma API
            gamma_endpoint = f"{self.BASE_URL}/prices-history"
            try:
                # print(f"Requesting Gamma: {gamma_endpoint} with params {params}")
                response = requests.get(gamma_endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                return data.get("history", [])
            except Exception as e2:
                print(f"Gamma History failed: {e2}")
                return []

    def fetch_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch the orderbook for a specific token ID from the CLOB API.

        Args:
             token_id (str): The CLOB token ID.

        Returns:
            Dict[str, Any]: The orderbook JSON response.
        """
        url = "https://clob.polymarket.com/book"
        params = {"token_id": token_id}

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if "404" not in str(e):
                print(f"Error fetching orderbook for {token_id}: {e}")
            return {}
