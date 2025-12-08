import os
from typing import Any, Optional

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON


def derive_creds() -> None:
    """
    Derive Polymarket L2 API credentials from a private key.
    """
    load_dotenv()
    pk: Optional[str] = os.getenv("POLYMARKET_API_KEY")  # User put private key here

    if not pk:
        print("Error: POLYMARKET_API_KEY not found in .env")
        return

    if not pk.startswith("0x"):
        print("Warning: Key does not start with 0x. Ensure it is a hex private key.")

    print("Deriving L2 API Credentials from Private Key...")

    try:
        # Initialize client with private key only (for key creation)
        print("Initializing ClobClient...", flush=True)
        client = ClobClient(
            host="https://clob.polymarket.com", key=pk, chain_id=POLYGON
        )

        # Create API Key
        print("Testing connection...", flush=True)
        try:
            print(f"Server Time: {client.get_server_time()}", flush=True)
        except Exception as e:
            print(f"Connection failed: {e}", flush=True)

        # Try deriving first
        # creds type is typically an object with api_key, secret, passphrase attributes
        creds: Any = None

        print("Calling derive_api_key()...", flush=True)
        try:
            creds = client.derive_api_key()
            print("Derived Credentials successfully.", flush=True)
        except Exception as e:
            print(f"derive_api_key failed: {e}", flush=True)
            print("Calling create_api_key()...", flush=True)
            creds = client.create_api_key()

        print("\nSUCCESS! Here are your L2 API Credentials:")
        print("--------------------------------------------------")
        print(f"Creds Object: {creds}")
        # Try to guess attributes if print doesn't show them
        # print(f"POLYMARKET_API_KEY={creds.api_key}")
        # print(f"POLYMARKET_SECRET={creds.secret}")
        # print(f"POLYMARKET_PASSPHRASE={creds.passphrase}")
        print("--------------------------------------------------")
        print("\nPlease update your .env file with these values.")
        print(
            "Replace the existing POLYMARKET_API_KEY (which is your private key) "
            "with the new API Key above,"
        )
        print(
            "OR keep your private key in a separate variable "
            "(e.g. POLYMARKET_PRIVATE_KEY) if you wish,"
        )
        print("but the collector expects these exact variable names.")

    except Exception as e:
        print(f"Error deriving credentials: {e}")


if __name__ == "__main__":
    derive_creds()
