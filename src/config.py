import os
from dotenv import load_dotenv

load_dotenv()

# Polymarket Credentials
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY")
POLYMARKET_SECRET = os.getenv("POLYMARKET_SECRET")
POLYMARKET_PASSPHRASE = os.getenv("POLYMARKET_PASSPHRASE")

# Kalshi Credentials
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH")

# Polymarket Tag IDs
# Discovered via API:
# - EPL: 306
# - Soccer: 100350
# - Sports: 1

# Kalshi Series Tickers
# - CS2: KXCSGOGAME
# - EPL: KXENGLISHPREMIERLEAGUE (Hypothetical/To be verified) or try searching "Premier League"

MARKET_CONFIG = {
    "CS2": {
        "polymarket_tag_id": None, # Use search or fetch all for now, or find "Counter-Strike" tag
        "kalshi_series_ticker": "KXCSGOGAME",
        "keywords": ["Counter-Strike", "CS2", "CS:GO"]
    },
    "EPL": {
        "polymarket_tag_id": "306", # English Premier League
        "kalshi_series_ticker": "KXENGLISHPREMIERLEAGUE", # Placeholder
        "keywords": ["Premier League", "EPL", "Soccer"]
    }
}
