"""
event_listener.py
------------------
Turns the p2pool.observer WebSocket "events" feed into Qt signals the
rest of the dashboard can listen to.

WHY THIS ISN'T PART OF api_client.py:
api_client.py deliberately knows nothing about PySide6 -- that's what
makes it easy to trust on its own. This file is the opposite: its
whole job IS bridging network events into the Qt world using a
QThread and Qt's Signal/Slot system. Keeping that bridging code here
instead of mixing it into api_client.py keeps that separation intact.

WHY A QThread, SPECIFICALLY:
A WebSocket connection sits there and waits for messages that could
arrive at any moment -- unlike our regular API calls, there's no
"ask once, get an answer right away." Waiting like that in Python
normally means asyncio, and asyncio needs its own event loop running
continuously. But Qt's main thread is ALREADY running its own event
loop forever (redrawing the window, handling clicks, etc). Two
"run forever" loops can't share one thread. So: the asyncio loop that
does the waiting runs on a second, separate thread (a QThread),
leaving Qt's main thread completely free to keep the GUI responsive.

WHY A Signal, SPECIFICALLY:
Qt has one hard rule: only the main thread may touch GUI widgets
(labels, tables, etc). Our listener runs on a different thread, so it
must NEVER call something like self.stat_x.setText() directly --
that can crash the app, or corrupt the display, in ways that are
painful to reproduce.

The fix is Signal/Slot. When background-thread code does
`self.new_event.emit(some_dict)`, Qt notices sender and receiver live
on different threads and automatically queues the delivery: the
connected slot doesn't run immediately on the background thread --
Qt schedules it to run on the MAIN thread instead, next time the main
event loop is free. You don't manage that queueing yourself; using a
Signal instead of a direct call is what makes Qt do it for you.
"""

import asyncio
import json

from PySide6.QtCore import QThread, Signal
import websockets

from api_client import Network


# Same subdomain-per-network pattern as api_client.py's _BASE_URLS --
# just wss:// (WebSocket Secure) instead of https://, and /api/events
# instead of a REST path.
#
# NOTE: this path is inferred from the naming convention every other
# endpoint in api_client.py follows -- it wasn't possible to confirm
# the literal URL text from the docs page directly (it kept 502ing).
# Worth a quick sanity check against the maintainer's docs page
# before you rely on this in production.
_EVENT_URLS = {
    Network.NORMAL: "wss://p2pool.observer/api/events",
    Network.MINI: "wss://mini.p2pool.observer/api/events",
    Network.NANO: "wss://nano.p2pool.observer/api/events",
}

# If the connection drops, wait this long before trying again. NOT
# instant -- an instant reconnect loop hammering a server that's
# already having trouble is exactly the behavior we're trying to
# avoid by switching to this API in the first place.
_RECONNECT_DELAY_SECONDS = 5

# How long to wait for one message before checking "should I stop
# now?" again. This is what lets stop() take effect within a few
# seconds instead of the thread being stuck inside recv() forever.
_RECV_TIMEOUT_SECONDS = 5


class P2PoolEventListener(QThread):
    """
    Runs a persistent WebSocket connection to p2pool.observer on a
    background thread, and emits new_event for every message
    received.

    Usage:
        listener = P2PoolEventListener(Network.MINI)
        listener.new_event.connect(some_slot_function)
        listener.start()      # begins running in the background
        ...
        listener.stop()       # ask it to shut down
        listener.wait(3000)   # block up to 3s for it to actually exit
    """

    # dict is the parsed JSON event, e.g. {"type": "found_block", ...}
    new_event = Signal(dict)

    def __init__(self, network: Network):
        super().__init__()
        self.network = network
        self.url = _EVENT_URLS[network]
        # Sentinel telling the running asyncio loop "time to stop."
        # A plain bool is safe to read/write across threads here --
        # Python's GIL makes single attribute accesses like this
        # atomic, and we never need anything fancier (like a Lock)
        # for a flag this simple.
        self._should_stop = False

    # ------------------------------------------------------------
    # QThread calls run() automatically, on the NEW thread, once you
    # call .start() from the main thread. Never call run() yourself
    # directly -- that would just execute it on whatever thread you
    # called it from, defeating the entire point of this class.
    # ------------------------------------------------------------
    def run(self):
        asyncio.run(self._listen_forever())

    async def _listen_forever(self):
        while not self._should_stop:
            try:
                async with websockets.connect(self.url) as websocket:
                    while not self._should_stop:
                        try:
                            raw_message = await asyncio.wait_for(
                                websocket.recv(), timeout=_RECV_TIMEOUT_SECONDS
                            )
                        except asyncio.TimeoutError:
                            # No message within the timeout -- totally
                            # normal, just loop back and check
                            # _should_stop again.
                            continue

                        try:
                            event = json.loads(raw_message)
                        except json.JSONDecodeError:
                            # Malformed message -- skip it rather than
                            # crashing the whole listener over one bad
                            # message from the server.
                            continue

                        self.new_event.emit(event)
            except (websockets.exceptions.WebSocketException, OSError):
                # Connection dropped, or never connected in the first
                # place (network hiccup, server restart, etc). Fall
                # through to the sleep below, then loop back around
                # and try again -- unless stop() was called meanwhile.
                pass

            if not self._should_stop:
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)

    def stop(self):
        """
        Call from the main thread when the window is closing. Just
        flips the flag -- the running loop notices within
        _RECV_TIMEOUT_SECONDS and exits on its own, rather than being
        killed mid-operation.
        """
        self._should_stop = True
