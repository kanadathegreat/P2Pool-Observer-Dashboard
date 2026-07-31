"""
api_client.py
--------------
Everything that talks to the p2pool.observer API lives in this one
file. Nothing here touches the GUI -- this module doesn't know or
care that PySide6 exists. That separation matters: it means we can
fully test and trust this file on its own (like we're about to,
below), and later, if something about the API ever changes, this is
the ONLY file that needs to change.

This is the grown-up version of test_connection.py from earlier --
same ideas (requests, headers, timeouts, error handling), but now
organized as a reusable class instead of a one-shot script, and
covering every endpoint the dashboard needs instead of just two.
"""

import json
import os
import time
from enum import Enum

import requests


# --- Network selection ----------------------------------------------
# An Enum is Python's way of saying "this value can only be one of a
# fixed, named set of options." We use one here instead of plain
# strings so that if you type Network.NORMAL, your editor can catch
# a typo immediately -- whereas a plain string like "normal" could be
# misspelled "noraml" and Python wouldn't notice until it failed.
class Network(Enum):
    NORMAL = "normal"
    MINI = "mini"
    NANO = "nano"


# Each network's API lives at its own subdomain. This dictionary maps
# the Enum values above to the correct base web address.
_BASE_URLS = {
    Network.NORMAL: "https://p2pool.observer/api",
    Network.MINI: "https://mini.p2pool.observer/api",
    Network.NANO: "https://nano.p2pool.observer/api",
}

# Same browser-identifying header we used in test_connection.py.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_REQUEST_TIMEOUT_SECONDS = 10


class P2PoolAPIError(Exception):
    """
    Our own custom error type. When something goes wrong talking to
    the API, we raise THIS instead of letting requests' raw error
    bubble up. Reason: the GUI code that calls this client only needs
    to know "the API call failed and here's why," not the dozen
    different underlying network exceptions requests could throw.
    One clear error type is easier to handle in one place later.
    """
    pass


class P2PoolClient:
    """
    One instance of this class represents "a connection to one
    network's API." Create one with the network you want:

        client = P2PoolClient(Network.MINI)
        info = client.get_pool_info()

    If the user switches networks in the GUI later, we just create a
    new P2PoolClient with a different Network value -- this class
    doesn't hold any state that would make that unsafe.
    """

    def __init__(self, network: Network, debug_dir: str = None):
        """
        network: which of the three P2Pool networks to talk to
        debug_dir: folder to save raw JSON responses into, for
                   troubleshooting. If None, no debug files are saved.
        """
        self.network = network
        self.base_url = _BASE_URLS[network]
        self.debug_dir = debug_dir

        if self.debug_dir:
            os.makedirs(self.debug_dir, exist_ok=True)

    # ------------------------------------------------------------
    # Internal helper -- every public method below funnels through
    # this one. This is where the shared behavior lives: building the
    # URL, sending the request, checking the status code, parsing
    # JSON, and saving a debug copy. Keeping this in ONE place means
    # every endpoint automatically gets the same error handling and
    # debug-saving, without repeating that code seven times.
    # ------------------------------------------------------------
    def _get(self, path: str, params: dict = None, debug_name: str = None):
        url = f"{self.base_url}{path}"

        try:
            response = requests.get(
                url, headers=_HEADERS, params=params, timeout=_REQUEST_TIMEOUT_SECONDS
            )
        except requests.exceptions.RequestException as error:
            # Covers no internet, DNS failure, connection refused,
            # timeout, etc -- anything where we never even got a
            # response back at all.
            raise P2PoolAPIError(f"Could not reach {url}: {error}") from error

        if response.status_code != 200:
            # Covers the API responding, but with an error -- a
            # bot-block page, a 404 for a bad wallet address, etc.
            # We include a bit of the response body in the error
            # since that's often where the useful explanation is.
            snippet = response.text[:200]
            raise P2PoolAPIError(
                f"{url} returned HTTP {response.status_code}: {snippet}"
            )

        try:
            data = response.json()
        except ValueError as error:
            raise P2PoolAPIError(
                f"{url} returned a 200 OK but the body wasn't valid JSON"
            ) from error

        if self.debug_dir and debug_name:
            self._save_debug_copy(debug_name, data)

        return data

    def _save_debug_copy(self, debug_name: str, data):
        """
        Saves the raw response to a file so you can inspect exactly
        what the API sent, the same way pool_info_debug.json helped
        us catch the seconds_since_last_block nesting issue earlier.

        Each endpoint gets its OWN file (e.g. pool_info_debug.json,
        found_blocks_debug.json), and each call OVERWRITES that same
        file rather than piling up new ones. That keeps the debug
        folder small and always shows the most recent call only,
        which is what's actually useful for troubleshooting.
        """
        debug_path = os.path.join(self.debug_dir, f"{debug_name}_debug.json")
        with open(debug_path, "w") as debug_file:
            json.dump(data, debug_file, indent=2)

    # ------------------------------------------------------------
    # Public methods -- one per API endpoint the dashboard needs.
    # Each one is a thin, clearly-named wrapper around _get().
    # ------------------------------------------------------------

    def get_pool_info(self) -> dict:
        """
        General P2Pool + Monero network status. This is the endpoint
        the dashboard polls every 300 seconds for most of the
        "Network" panel's numbers.

        Remember: fields like block_time and difficulty live INSIDE
        the "sidechain" key, not at the top level -- see the note in
        parse_pool_info() below.
        """
        return self._get("/pool_info", debug_name="pool_info")

    def get_found_blocks(self, limit: int = 3, miner: str = None) -> list:
        """
        Recent Monero blocks that P2Pool has found. Used for
        "time since last block" and the "last 3 blocks" table.

        miner: if given, only returns blocks found by that specific
               wallet (we don't use this yet, but the API supports it).
        """
        params = {"limit": limit}
        if miner:
            params["miner"] = miner
        return self._get("/found_blocks", params=params, debug_name="found_blocks")

    def get_miner_info(self, address: str) -> dict:
        """
        General info for one wallet: mainly gives us
        last_share_timestamp, which is the "Last share found by
        wallet" field.
        """
        return self._get(f"/miner_info/{address}", debug_name="miner_info")

    def get_side_blocks_in_window(self, address: str, window: int = None) -> list:
        """
        The list of this wallet's shares currently counted in the
        PPLNS payout window. The LENGTH of this list is the "Current
        Active Shares" number. The first few entries (most recent)
        are what we use for the "share age / expiration" table.

        window: how many sidechain blocks back to look. If None, the
                API defaults to the current live window. We'll pass a
                specific larger number later to approximate "shares
                in the last 24 hours."
        """
        params = {}
        if window is not None:
            params["window"] = window
        return self._get(
            f"/side_blocks_in_window/{address}",
            params=params,
            debug_name="side_blocks_in_window",
        )

    def get_all_side_blocks_in_window(self, window: int = None) -> list:
        """
        Same idea as get_side_blocks_in_window(), but network-wide --
        every miner's shares in the window, not just one wallet's.
        We use the LENGTH of this list as "total shares in the
        window" when estimating a wallet's proportional payout.
        """
        params = {}
        if window is not None:
            params["window"] = window
        return self._get(
            "/side_blocks_in_window",
            params=params,
            debug_name="all_side_blocks_in_window",
        )

    def get_network_side_blocks_in_window(self, window: int = None) -> list:
        """
        Same as get_side_blocks_in_window(), but for EVERY miner, not
        just one wallet. We use the length of this list as "total
        shares in the current window" -- needed to estimate what
        fraction of the window belongs to one wallet, which is how
        we estimate that wallet's window reward.
        """
        params = {}
        if window is not None:
            params["window"] = window
        return self._get(
            "/side_blocks_in_window",
            params=params,
            debug_name="network_side_blocks_in_window",
        )

    def get_shares(self, miner: str = None, limit: int = 50, only_blocks: bool = False) -> list:
        """
        Raw share records. We mainly use this as a fallback / cross
        check against side_blocks_in_window.
        """
        params = {"limit": limit}
        if miner:
            params["miner"] = miner
        if only_blocks:
            params["onlyBlocks"] = "true"
        return self._get("/shares", params=params, debug_name="shares")

    def get_payouts(self, address: str, search_limit: int = 10) -> list:
        """
        Actual Monero payouts this wallet has received from blocks
        P2Pool found. Not required for the core dashboard fields, but
        useful later if we ever add payout history.
        """
        params = {"search_limit": search_limit}
        return self._get(f"/payouts/{address}", params=params, debug_name="payouts")


# --- Derived values (pure math, no network calls) --------------------
# These functions take numbers we ALREADY fetched and calculate
# something useful from them. They're kept separate from the class
# above on purpose: the class's job is "get data from the internet,"
# these functions' job is "do math on data we already have." Mixing
# the two would make both harder to test.

def calculate_hashrate(difficulty: float, block_time_seconds: float) -> float:
    """
    Returns hashrate in H/s (hashes per second).

    The formula is: hashrate = difficulty / block_time.

    Why this works: "difficulty" is defined, by design, as roughly
    "how many hash attempts it takes, on average, to find one block
    at the current block time." So dividing by how many seconds each
    block actually takes converts that into hashes-per-second.

    IMPORTANT: block_time_seconds is NOT the same for every network.
    Mini uses 10 seconds, Nano uses 30 seconds -- we confirmed this
    by reading real example data from both networks' docs, not by
    assuming. ALWAYS pass in the block_time value that came from that
    network's own pool_info response, never a hardcoded number.
    """
    if not block_time_seconds:
        raise ValueError("block_time_seconds must be a nonzero number")
    return difficulty / block_time_seconds


def format_hashrate(hashrate_hs: float) -> str:
    """
    Converts a raw H/s number into a friendly string like "22.4 MH/s"
    instead of showing an ugly 8-digit number. Steps up through
    H/s -> kH/s -> MH/s -> GH/s, same idea as how file sizes step up
    through bytes -> KB -> MB -> GB.
    """
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s"]
    value = hashrate_hs
    unit_index = 0

    while value >= 1000 and unit_index < len(units) - 1:
        value /= 1000
        unit_index += 1

    return f"{value:,.2f} {units[unit_index]}"


def seconds_to_friendly_duration(total_seconds: float) -> str:
    """
    Converts a raw number of seconds into something readable, like
    "2h 14m" or "45s". Used for "time since last block," the share
    expiration countdowns, etc.
    """
    total_seconds = int(total_seconds)
    if total_seconds < 0:
        return "expired"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"
