"""
config.py
---------
Handles remembering things between runs of the program: which
network you last used, and every wallet address you've tracked
(along with which network each one belongs to).

This works by reading and writing a small JSON file on disk. JSON is
just a plain-text way of storing structured data -- Python's dicts
and lists convert to/from it almost automatically, which is why it's
such a common choice for small settings files like this one.

Like api_client.py, this file doesn't know anything about the GUI.
It just manages a file on disk. That separation means we can test it
completely on its own, which is exactly what test_config.py does.
"""

import json
import os
import time


class ConfigManager:
    """
    One instance of this class represents "the saved settings file."
    Create one, call .load() once at startup, read/change its data,
    and call .save() whenever something changes.

    Usage:
        config = ConfigManager("cache/config.json")
        config.load()

        config.set_last_network("mini")
        config.add_wallet("mini", "47ab14Eok...")
        config.save()

        print(config.get_last_network())
        print(config.get_wallets_for_network("mini"))
    """

    def __init__(self, config_path: str):
        self.config_path = config_path

        # This is the in-memory copy of the settings. It starts as a
        # sensible empty default -- if the file on disk doesn't exist
        # yet (first time running the program ever), we still have a
        # valid structure to work with instead of crashing.
        self._data = {
            "last_network": None,
            # Not tied to any network or wallet -- just a general app
            # preference, so it lives at this top level rather than
            # inside the per-network "wallets" section below.
            "preferred_currency": "usd",
            # "wallets" maps a network name ("mini", "normal", "nano")
            # to a LIST of wallet entries used on that network. Each
            # entry remembers the address and when it was last used,
            # so the dropdown can show most-recent-first later.
            "wallets": {
                "normal": [],
                "mini": [],
                "nano": [],
            },
        }

    # ------------------------------------------------------------
    # Loading and saving
    # ------------------------------------------------------------
    def load(self):
        """
        Reads the settings file from disk into memory. Safe to call
        even if the file doesn't exist yet, or is somehow broken --
        in both cases we just quietly fall back to the empty
        defaults set up in __init__, rather than crashing the whole
        program over a settings file.
        """
        if not os.path.exists(self.config_path):
            # Nothing to load -- this is normal on first run.
            return

        try:
            with open(self.config_path, "r") as config_file:
                loaded = json.load(config_file)
        except (json.JSONDecodeError, OSError):
            # The file exists but is unreadable or corrupted (e.g. it
            # got cut off mid-write during a crash). We choose to
            # keep running with defaults rather than crash the app
            # over a broken settings file -- worst case, you just
            # have to re-pick your network and re-enter a wallet.
            return

        # We merge rather than blindly overwrite, in case a future
        # version of this program adds new settings keys that an
        # older saved file wouldn't have. This way old files still
        # load fine, just missing the new keys (which keep their
        # defaults).
        self._data.update(loaded)

    def save(self):
        """
        Writes the current in-memory settings out to disk as JSON.
        Creates the containing folder if it doesn't exist yet.
        """
        folder = os.path.dirname(self.config_path)
        if folder:
            os.makedirs(folder, exist_ok=True)

        with open(self.config_path, "w") as config_file:
            json.dump(self._data, config_file, indent=2)

    # ------------------------------------------------------------
    # Last-used network
    # ------------------------------------------------------------
    def get_last_network(self) -> str:
        """Returns 'normal', 'mini', 'nano', or None if never set."""
        return self._data.get("last_network")

    def set_last_network(self, network_name: str):
        self._data["last_network"] = network_name

    # ------------------------------------------------------------
    # Preferred currency (for the XMR converter)
    # ------------------------------------------------------------
    def get_preferred_currency(self) -> str:
        """Returns 'usd', 'gbp', or 'eur'. Defaults to 'usd'."""
        return self._data.get("preferred_currency", "usd")

    def set_preferred_currency(self, currency_code: str):
        self._data["preferred_currency"] = currency_code

    # ------------------------------------------------------------
    # Wallet history
    # ------------------------------------------------------------
    def add_wallet(self, network_name: str, address: str):
        """
        Records that this wallet address was used on this network,
        for the "recently tracked wallets" dropdown.

        If the address is already saved for this network, we don't
        add a duplicate -- we just update its "last used" time and
        move it to the front, so the dropdown naturally shows
        most-recently-used wallets first.
        """
        wallets = self._data["wallets"].setdefault(network_name, [])

        # Remove any existing entry for this exact address first, so
        # we don't end up with two rows for the same wallet.
        wallets[:] = [entry for entry in wallets if entry["address"] != address]

        wallets.insert(0, {
            "address": address,
            "last_used": time.time(),
        })

    def get_wallets_for_network(self, network_name: str) -> list:
        """
        Returns the list of saved wallet addresses for one network,
        most-recently-used first. Just the address strings -- the
        GUI dropdown doesn't need the raw timestamp, only the order
        it implies (which we've already sorted by, above).
        """
        wallets = self._data["wallets"].get(network_name, [])
        return [entry["address"] for entry in wallets]

    def clear_all_wallets(self):
        """
        Wipes every saved wallet address on every network. Used by
        the startup dialog's "purge saved wallets" button.

        This does NOT touch last_network -- purging wallet history
        and forgetting which network you last used are two different
        things, and there's no reason clearing one should reset the
        other. If that assumption is wrong, this is a one-line change.

        IMPORTANT: this only clears the in-memory copy. Like every
        other change in this class, it isn't permanent until save()
        is called afterward -- this keeps the same pattern as
        add_wallet() and set_last_network(), so the GUI's "click
        button -> confirm -> save()" flow works the same way for all
        of them.
        """
        self._data["wallets"] = {
            "normal": [],
            "mini": [],
            "nano": [],
        }
