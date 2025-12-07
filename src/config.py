import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()

# Polymarket Credentials
POLYMARKET_API_KEY: Optional[str] = os.getenv("POLYMARKET_API_KEY")
POLYMARKET_SECRET: Optional[str] = os.getenv("POLYMARKET_SECRET")
POLYMARKET_PASSPHRASE: Optional[str] = os.getenv("POLYMARKET_PASSPHRASE")
POLYMARKET_PRIVATE_KEY: Optional[str] = os.getenv("POLYMARKET_PRIVATE_KEY")

# Kalshi Credentials
KALSHI_API_KEY_ID: Optional[str] = os.getenv("KALSHI_API_KEY_ID")
KALSHI_PRIVATE_KEY_PATH: Optional[str] = os.getenv("KALSHI_PRIVATE_KEY_PATH")

# Polymarket Tag IDs
# Discovered via API
# - EPL: 306
# - Soccer: 100350
# - Sports: 1

# Kalshi Series Tickers
# - CS2: KXCSGOGAME

MARKET_CONFIG: Dict[str, Dict[str, Optional[Any]]] = {
    "CS2": {
        "polymarket_tag_id": None,
        "kalshi_series_ticker": "KXCSGOGAME",
        "keywords": ["Counter-Strike", "CS2", "CS:GO"],
    },
    "EPL": {
        "polymarket_tag_id": "306",
        "kalshi_series_ticker": "KXENGLISHPREMIERLEAGUE",
        "keywords": ["Premier League", "EPL", "Soccer"],
    },
}
