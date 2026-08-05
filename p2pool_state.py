"""
p2pool_state.py
-----------------
A local, continuously-updated mirror of "the current P2Pool window" --
the numbers the dashboard used to get by re-asking the REST API every
300 seconds, now kept up to date incrementally from the WebSocket
event stream instead.

Like api_client.py, this file knows nothing about PySide6. It's pure
data and calculation: events go IN through apply_event(), and the
dashboard's numbers come OUT through the attributes/properties near
the bottom. That split means this class can be tested completely on
its own -- feed it fake events, check the numbers come out right --
same reasoning api_client.py's own docstring gives for staying
separate from the GUI.

WHY THIS FILE DOESN'T TRACK THE WHOLE NETWORK'S WINDOW ANYMORE:
An earlier version of this file kept a full copy of EVERY miner's
shares in the current window, built by calling
get_all_side_blocks_in_window() once at startup. That was needlessly
heavy: pool_info already hands back the two numbers we actually
wanted from that data --

    sidechain.window.miners  -> how many miners are in the window
    sidechain.window.blocks  -> how many shares are in the window

-- pre-counted, on the server, in one lightweight call. Fetching and
counting every individual share ourselves was doing the server's own
work over again, for the same answer -- exactly what the admin
flagged as processing-heavy. So now:
    - Network-wide totals (window_miner_count, total_shares_in_window)
      come straight from pool_info, refreshed each bootstrap() call
      (startup + manual "Refresh Now"). They're a SNAPSHOT, not a
      live-ticking number -- see the note on those two attributes
      below for why, and what your options are if you want them
      fresher later.
    - Height and difficulty DO update live, every side_block/
      found_block event carries its own -- no heavy call needed for
      those either, network-wide or not.
    - Only YOUR wallet's shares are tracked share-by-share, since
      that's the only per-share detail this dashboard actually shows
      (active shares, 24h count, share-age table) -- and the REST
      call for that was always wallet-scoped and small to begin with.

CONFIRMED FIELD MATCH: checked directly against the API docs -- the
JSON objects inside side_block events and the rows
/api/side_blocks_in_window returns use the exact same field names
(side_height, miner_address, difficulty, timestamp, etc). That's
what makes it safe to store one incoming event the same way we'd
store one REST row -- same shape.

ONE APPROXIMATION, FLAGGED HONESTLY: found_block events don't carry
their own top-level "timestamp" the way side_block events do -- only
a timestamp on the MAIN CHAIN block they found. We use that as a
stand-in for the share's own time, accurate to within one P2Pool
share interval (a few seconds to half a minute) -- fine for window/
age math, but worth knowing it's a stand-in, not an exact field
match.

ONE KNOWN LIMITATION: if the current chain TIP itself gets orphaned
(rare -- it means the share we thought just won gets replaced by a
competing one), height/difficulty won't roll back to the previous
value here. They'll just sit one step stale until the next real
side_block event corrects them. Tracking the "previous" value too
would mean going back to keeping a fuller network-wide history --
exactly the cost this redesign was written to avoid -- so this is a
deliberate trade, not an oversight.
"""

import time


class P2PoolLiveState:
    def __init__(self, wallet_address: str = None):
        self.wallet_address = wallet_address

        # Static per-network facts, set once in bootstrap() and never
        # touched by events afterward.
        self.block_time_seconds = None
        self.window_size_blocks = None
        self.window_duration_seconds = None

        # Current chain tip. Set at bootstrap, then kept live-updated
        # by every side_block/found_block event from here on --
        # this pair doesn't depend on the heavy network-wide call at
        # all, live or not.
        self.height = None
        self.difficulty = None

        # Network-wide totals. SNAPSHOT values, not live -- only
        # updated when bootstrap() runs (startup + manual refresh).
        # Getting these to update on every event would mean tracking
        # every miner's shares locally, which is the exact cost this
        # file was rewritten to avoid. If you want these fresher than
        # "once per manual refresh" later, the cheap middle ground is
        # a periodic pool_info-ONLY re-fetch (that single call is
        # lightweight -- it's the per-share enumeration that wasn't).
        self.window_miner_count = 0
        self.total_shares_in_window = 0

        # --- PPLNS "weight" tracking ---
        # Added after confirming (against real debug JSON, not a
        # guess) that "my share count / total share count" is NOT how
        # P2Pool actually decides payouts. The real currency is
        # "weight": each share's difficulty, adjusted for uncles.
        # See _share_weight() below for the exact math and what's
        # been confirmed vs. not.
        #
        # All three of these are SNAPSHOT values, same cadence as
        # window_miner_count/total_shares_in_window right above --
        # only bootstrap() and refresh_network_totals() touch them.
        self.pool_window_weight = 0     # sidechain.window.weight
        self.uncle_penalty_percent = 0  # sidechain.uncle_penalty (e.g. 20)
        self.base_reward_atomic = 0     # mainchain.base_reward

        # Our wallet's own shares, newest first. This is the only
        # per-share list this file keeps -- small by construction,
        # since the REST call that seeds it is already wallet-scoped.
        # Covers three different things depending on how it's read:
        #   - length                              -> shares in ~24h
        #   - filtered to inside the window        -> active shares
        #   - same filtered set, newest first       -> share-age table
        self._wallet_shares = []

        # Recent actual Monero blocks found -- newest first, same
        # shape/order the found_blocks REST endpoint used.
        self.recent_found_blocks = []

        # Wallet's recent payouts -- newest first. Field names are
        # normalized to match what /api/payouts used, so render code
        # doesn't need to know which source a given entry came from.
        self.wallet_recent_payouts = []

    # ------------------------------------------------------------
    # Bootstrap -- call ONCE, right after the startup REST calls
    # main_window.py already makes. Everything after this comes from
    # apply_event() instead of asking the server again, EXCEPT the
    # two network-wide totals noted above, which only bootstrap()
    # updates.
    # ------------------------------------------------------------
    def bootstrap(self, pool_info, found_blocks, wallet_recent_shares, payouts):
        side = pool_info["sidechain"]
        consensus = side["consensus"]
        self.block_time_seconds = consensus["block_time"]
        self.window_size_blocks = consensus["pplns_window"]
        self.window_duration_seconds = self.window_size_blocks * self.block_time_seconds

        last_block = side["last_block"]
        self.height = last_block["side_height"]
        self.difficulty = last_block["difficulty"]

        window = side["window"]
        self.window_miner_count = window["miners"]
        self.total_shares_in_window = window["blocks"]
        self.pool_window_weight = window["weight"]

        # NOTE: "uncle_penalty" lives directly under sidechain, not
        # under sidechain.window. "base_reward" lives under
        # "mainchain" -- CONFIRMED spelled with no underscore, one
        # word, against a real pool_info debug file. It's an easy typo
        # to make (main_chain reads more natural) and it fails
        # silently -- a wrong key just gives you a KeyError, or worse,
        # a 0 that quietly makes every reward estimate show as 0.
        self.uncle_penalty_percent = side["uncle_penalty"]
        self.base_reward_atomic = pool_info["mainchain"]["base_reward"]

        self._wallet_shares = list(wallet_recent_shares)
        self.recent_found_blocks = list(found_blocks)
        self.wallet_recent_payouts = list(payouts)

    def refresh_network_totals(self, pool_info):
        """
        Lighter cousin of bootstrap() -- updates ONLY the network-wide
        snapshot numbers (window_miner_count, total_shares_in_window,
        and now the three weight-related fields alongside them) from
        a fresh pool_info call. Doesn't touch height/difficulty
        (already kept current by every side_block/found_block event)
        or any wallet-specific data.

        Meant to be called on some occasional trigger -- see
        main_window.py's _on_p2pool_event(), which calls this
        whenever a found_block event arrives. A real Monero block
        being found is a naturally infrequent, meaningful checkpoint
        -- far rarer than side_block events -- which makes it a
        reasonable moment to spend one light pool_info call refreshing
        these numbers, without needing a timer or the heavy per-share
        call this file was rewritten to avoid.

        Refreshing pool_window_weight and base_reward_atomic here
        matters more than it might look: base_reward shifts a little
        with every Monero block (transaction fees change it slightly),
        and pool_window_weight shifts as old shares age out of the
        window and new ones come in. A found_block event is exactly
        the moment both of those are most likely to have moved.
        """
        window = pool_info["sidechain"]["window"]
        self.window_miner_count = window["miners"]
        self.total_shares_in_window = window["blocks"]
        self.pool_window_weight = window["weight"]
        self.uncle_penalty_percent = pool_info["sidechain"]["uncle_penalty"]
        self.base_reward_atomic = pool_info["mainchain"]["base_reward"]

    # ------------------------------------------------------------
    # Event handling -- call for every event the listener emits.
    # ------------------------------------------------------------
    def apply_event(self, event: dict):
        event_type = event.get("type")
        if event_type == "side_block":
            self._apply_tip_update(event["side_block"])
        elif event_type == "found_block":
            self._apply_found_block(event["found_block"])
        elif event_type == "orphaned_block":
            # The server doesn't document this payload's exact shape
            # (the docs page cut the example for size), but every
            # other event nests its data under a key matching the
            # type name -- side_block under "side_block", found_block
            # under "found_block" -- so orphaned_block under
            # "orphaned_block" is the same pattern, not a guess made
            # from nothing.
            self._apply_orphaned(event.get("orphaned_block", {}))

    def _apply_tip_update(self, share: dict):
        """
        Handles a single share -- ANY miner's, not just ours. Height
        and difficulty are network facts, so every share advances
        them. Only appends to our own wallet list if it's actually
        our share.
        """
        height = share.get("side_height")
        if height is not None:
            self.height = height
            self.difficulty = share.get("difficulty", self.difficulty)

        if self.wallet_address and share.get("miner_address") == self.wallet_address:
            self._wallet_shares.insert(0, share)
            self._trim_wallet_shares()

    def _apply_found_block(self, found_block: dict):
        main_block = found_block["main_block"]

        # A found block IS also a share -- update the tip and our own
        # share list the same way, using main_block's timestamp as
        # the approximation the class docstring above explains.
        share_like = dict(found_block)
        share_like["timestamp"] = main_block["timestamp"]
        self._apply_tip_update(share_like)

        self.recent_found_blocks.insert(0, found_block)
        self.recent_found_blocks = self.recent_found_blocks[:3]

        if self.wallet_address:
            for output in found_block.get("main_coinbase_outputs", []):
                if output.get("miner_address") == self.wallet_address:
                    self.wallet_recent_payouts.insert(0, {
                        "coinbase_reward": output["value"],
                        "timestamp": main_block["timestamp"],
                        "coinbase_id": output.get("id"),
                    })
            self.wallet_recent_payouts = self.wallet_recent_payouts[:5]

    def _apply_orphaned(self, orphaned: dict):
        height = orphaned.get("side_height")
        if height is not None:
            self._wallet_shares = [
                s for s in self._wallet_shares if s.get("side_height") != height
            ]
        # height/difficulty are deliberately NOT rolled back here --
        # see "ONE KNOWN LIMITATION" at the top of this file.

    def _trim_wallet_shares(self):
        cutoff = time.time() - 86400
        self._wallet_shares = [
            s for s in self._wallet_shares if s.get("timestamp", 0) >= cutoff
        ]

    def _shares_still_in_window(self):
        """
        Our wallet's shares whose side_height hasn't fallen out of
        the current PPLNS window yet -- the subset of the 24h list
        that's still actually "active" for payout purposes.
        """
        if self.height is None or self.window_size_blocks is None:
            return []
        cutoff = self.height - self.window_size_blocks
        return [s for s in self._wallet_shares if s.get("side_height", -1) > cutoff]

    def _share_weight(self, share: dict) -> float:
        """
        Works out ONE share's real PPLNS weight -- the number that
        actually decides its slice of a payout. NOT the same thing as
        the share's raw "difficulty" field, though for most shares
        (ones that didn't include an uncle) they happen to be equal.

        CONFIRMED against a real side_blocks_in_window debug file: a
        share dict that included one or more uncles carries an
        "uncles" list, and each entry in that list is its own little
        dict with its own "difficulty". A share that included NO
        uncles just doesn't have the "uncles" key at all (it's not an
        empty list -- it's flat-out missing), which is why we read it
        with .get("uncles", []) below instead of ["uncles"].

        The math itself, confirmed against api.go's PPLNS weight
        calculation and P2Pool's own uncle-penalty docs:
          - A share that included uncles gets its OWN full difficulty,
            PLUS a bonus worth uncle_penalty_percent of each included
            uncle's difficulty. (On Mini and Main, that's 20% as of
            writing -- but we always read the live value from
            pool_info instead of hardcoding 20, in case it's ever
            different on Nano, or changes in the future.)
          - The other side of that penalty: an uncle share only
            counts for the REMAINING (100 - uncle_penalty_percent)
            percent of its own difficulty, since some of its value
            went to whichever share included it as a bonus. Nothing
            is created or destroyed overall -- it's a transfer, not a
            loss.

        ONE THING NOT YET CONFIRMED WITH REAL DATA: whether one of
        YOUR OWN shares that became somebody else's uncle would even
        show up as its own top-level entry when you call
        side_blocks_in_window for your address, and if it did, which
        field would mark it as an uncle share rather than a normal
        one. Every real share pulled so far (19 of them, in the debug
        file this was built against) was a normal share, so that
        second bullet above has never actually been exercised against
        real data -- only reasoned out from the docs and api.go. If
        you ever spot a share in a fresh debug file that looks like
        it might be an uncle, that's the moment to come back to this
        function and confirm the second bullet properly.
        """
        penalty_fraction = self.uncle_penalty_percent / 100

        # The bonus this share earns for each uncle IT included.
        uncle_bonus = sum(
            uncle.get("difficulty", 0) * penalty_fraction
            for uncle in share.get("uncles", [])
        )

        return share.get("difficulty", 0) + uncle_bonus

    # ------------------------------------------------------------
    # Derived values -- read by main_window.py every time it wants to
    # redraw. All pure calculation on data already in memory; no
    # network calls happen anywhere in this class.
    # ------------------------------------------------------------
    @property
    def wallet_active_shares(self):
        if not self.wallet_address:
            return 0
        return len(self._shares_still_in_window())

    @property
    def wallet_window_weight(self):
        """
        Sum of _share_weight() across every one of this wallet's
        shares still counted in the current PPLNS window. This is
        the correct numerator for "how much of the pool is mine" --
        NOT wallet_active_shares (a plain count), which treats a big
        share and a small share as worth the same amount.
        """
        return sum(self._share_weight(s) for s in self._shares_still_in_window())

    @property
    def wallet_pool_share_percent(self):
        """
        What percentage of the current PPLNS window belongs to this
        wallet, by weight. This is the number p2pool.observer's own
        miner page calls "Pool Share %" -- and it's a weight-based
        fraction, not a share-count-based one, which is exactly the
        distinction that started this whole investigation.

        Guards against dividing by zero for the brief moment right
        after startup, before bootstrap() has run and
        pool_window_weight is still its initial 0.
        """
        if not self.pool_window_weight:
            return 0.0
        return self.wallet_window_weight / self.pool_window_weight * 100

    @property
    def wallet_estimated_window_reward_atomic(self):
        """
        This wallet's estimated slice of the reward, IF the pool
        found a Monero block right now, in atomic units -- run it
        through api_client.atomic_to_xmr() before putting it on
        screen.

        Read the word "estimated" seriously: this is a snapshot, not
        a promise. Both pieces it's built from keep moving --
        base_reward_atomic shifts slightly with transaction fees on
        whatever block gets found, and the window's contents (and
        therefore wallet_pool_share_percent) shift as old shares age
        out and new ones come in. Treat this as "about this much,
        roughly, right now" -- the same way p2pool.observer's own
        "Estimated Window Reward" field behaves.
        """
        return self.wallet_pool_share_percent / 100 * self.base_reward_atomic

    @property
    def wallet_shares_last_24h(self):
        return len(self._wallet_shares)

    @property
    def wallet_last_share_ts(self):
        if not self._wallet_shares:
            return None
        return self._wallet_shares[0].get("timestamp")

    def wallet_share_age_rows(self, row_count=3):
        """
        Returns up to row_count of the wallet's still-active shares,
        newest first, each as (found_ts, expires_at). Mirrors the
        shape main_window.py's share_age_table already expects.
        """
        rows = []
        for share in self._shares_still_in_window()[:row_count]:
            found_ts = share.get("timestamp")
            if found_ts is None or self.window_duration_seconds is None:
                continue
            rows.append((found_ts, found_ts + self.window_duration_seconds))
        return rows
