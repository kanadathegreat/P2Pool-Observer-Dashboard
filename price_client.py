"""
price_client.py
-----------------
Fetches the current XMR (Monero) price in USD, GBP, and EUR from
CoinGecko's free API. Kept in its own file, separate from
api_client.py, because this talks to a completely different service
(CoinGecko, not p2pool.observer) -- no reason to mix the two.

CoinGecko's free tier needs no API key/signup for this endpoint.
"""

import requests


class PriceAPIError(Exception):
    """Same idea as P2PoolAPIError in api_client.py -- one clear
    error type for the GUI to catch, instead of several raw
    exception types from requests."""
    pass


_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_REQUEST_TIMEOUT_SECONDS = 10


def get_xmr_prices() -> dict:
    """
    Returns a dict like {"usd": 158.32, "gbp": 124.11, "eur": 145.67}.
    Raises PriceAPIError if the fetch fails for any reason.
    """
    params = {"ids": "monero", "vs_currencies": "usd,gbp,eur"}

    try:
        response = requests.get(
            _PRICE_URL, headers=_HEADERS, params=params, timeout=_REQUEST_TIMEOUT_SECONDS
        )
    except requests.exceptions.RequestException as error:
        raise PriceAPIError(f"Could not reach CoinGecko: {error}") from error

    if response.status_code != 200:
        raise PriceAPIError(f"CoinGecko returned HTTP {response.status_code}")

    try:
        data = response.json()
        return data["monero"]  # {"usd": ..., "gbp": ..., "eur": ...}
    except (ValueError, KeyError) as error:
        raise PriceAPIError(f"Unexpected response shape from CoinGecko: {error}") from error
