"""
main_window.py
----------------
The real dashboard window. Same visual shell as GUI Test's main.py,
wired to live data two ways now:
  - ONE full REST fetch at startup (and again if the user clicks
    Refresh Now), via refresh_data() / p2pool_state.bootstrap().
  - Everything after that arrives over the WebSocket event stream
    (event_listener.py) and updates p2pool_state.py's local shadow
    of the P2Pool window -- no more periodic REST polling for P2Pool
    data specifically.
The one thing still on a timer is the XMR price converter, since
that's a separate API (CoinGecko) with no push/event mechanism at
all -- see PRICE_REFRESH_SECONDS below.
"""

import os
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QComboBox,
)
from PySide6.QtCore import Qt, QTimer, QRegularExpression
from PySide6.QtGui import QPixmap, QIcon, QPainter, QPainterPath, QRegularExpressionValidator

import theme
from graph_widget import HashrateGraphWidget
from help_window import HelpWindow
from price_client import get_xmr_prices, PriceAPIError
from api_client import (
    Network, P2PoolClient, P2PoolAPIError,
    calculate_hashrate, format_hashrate, seconds_to_friendly_duration,
    atomic_to_xmr,
)
from event_listener import P2PoolEventListener
from p2pool_state import P2PoolLiveState

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, "assets", "logo.jpeg")

REFRESH_COOLDOWN_SECONDS = 30
# Only governs the XMR price converter now -- P2Pool's own numbers no
# longer refresh on a timer at all, they update live from events.
PRICE_REFRESH_SECONDS = 300

_NETWORK_LABELS = {Network.NORMAL: "Normal", Network.MINI: "Mini", Network.NANO: "Nano"}

# Roughly how many sidechain blocks make up 24 hours, used to fetch
# "shares in the last day." This is a starting estimate per network
# (86400 seconds / typical block_time) -- we refine it with the real
# block_time from pool_info once we have it, each refresh.
_APPROX_DAY_WINDOW = {Network.NORMAL: 8640, Network.MINI: 8640, Network.NANO: 2880}


def rounded_pixmap(source_pixmap, radius):
    """Same technique as GUI Test: clip an image's corners via a stencil path."""
    rounded = QPixmap(source_pixmap.size())
    rounded.fill(Qt.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)
    clip_path = QPainterPath()
    clip_path.addRoundedRect(0, 0, source_pixmap.width(), source_pixmap.height(), radius, radius)
    painter.setClipPath(clip_path)
    painter.drawPixmap(0, 0, source_pixmap)
    painter.end()
    return rounded


def make_stat_row(grid_layout, row, label_text, tooltip_text=""):
    caption = QLabel(label_text)
    caption.setProperty("subtext", "true")
    value = QLabel("--")
    if tooltip_text:
        caption.setToolTip(tooltip_text)
        value.setToolTip(tooltip_text)
    grid_layout.addWidget(caption, row, 0)
    grid_layout.addWidget(value, row, 1)
    return value


def make_table(headers, row_count):
    table = QTableWidget(row_count, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    for r in range(row_count):
        for c in range(len(headers)):
            table.setItem(r, c, QTableWidgetItem("--"))

    # Figure out the ACTUAL height needed instead of guessing a fixed
    # pixel-per-row number. The previous version assumed 28px/row,
    # but the real rendered row height depends on font size and the
    # theme's CSS padding -- guessing came in a few pixels short and
    # clipped the bottom row. resizeRowsToContents() asks Qt to size
    # each row to fit what's actually in it, THEN we measure that
    # real size and use it, rather than assuming a number up front.
    table.resizeRowsToContents()
    row_height = table.verticalHeader().sectionSize(0) if row_count > 0 else 0
    header_height = table.horizontalHeader().height()
    frame = table.frameWidth() * 2
    # +2px slack so we're never off-by-one short due to rounding.
    total_height = header_height + (row_height * row_count) + frame + 2
    table.setFixedHeight(total_height)

    return table


class MainWindow(QMainWindow):
    def __init__(self, network: Network, wallet_address: str, config):
        super().__init__()
        self.network = network
        self.wallet_address = wallet_address
        self.config = config
        self.client = P2PoolClient(network, debug_dir="cache/debug")
        self.live_state = P2PoolLiveState(wallet_address)

        self.setWindowTitle(f"P2Pool Observer Dashboard — {_NETWORK_LABELS[network]}")
        self.resize(1600, 900)
        if os.path.exists(LOGO_PATH):
            self.setWindowIcon(QIcon(LOGO_PATH))

        central = QWidget()
        self.setCentralWidget(central)
        master_layout = QVBoxLayout(central)
        master_layout.setContentsMargins(16, 16, 16, 16)
        master_layout.setSpacing(14)
        master_layout.addLayout(self._build_top_bar())
        # stretch=1 on the panels row means IT absorbs any extra
        # window height on resize -- the converter bar below keeps
        # its own natural (small) height instead of stretching too.
        master_layout.addLayout(self._build_body(), 1)
        master_layout.addWidget(self._build_converter_panel())

        self.statusBar().showMessage("Loading...")

        # -- Timers --------------------------------------------------
        # One 1-second timer drives BOTH visible countdowns (manual
        # cooldown + next price refresh), since they're both just "a
        # number that ticks down once a second." A separate timer per
        # countdown would do the same job with more moving parts.
        self._cooldown_seconds_left = 0
        self._seconds_until_price_refresh = PRICE_REFRESH_SECONDS
        # Set once per refresh from found_blocks (the actual Monero
        # blocks P2Pool has found) -- NOT from the sidechain's own
        # block churn, which happens every few seconds and would make
        # this stat meaningless. _on_tick() below counts up from this
        # every second, independent of the 300-second refresh cycle.
        self._last_monero_block_ts = None
        # One expiration timestamp per row in the share age table
        # (or None for an empty row). _on_tick() uses this to redraw
        # the "Expires In" countdown every second; refresh_data()
        # resets it to the freshly-fetched values, keeping the two in
        # sync without fighting each other.
        self._share_expiry_data = [None, None, None]
        # One "found at" timestamp per row in the payout table (or
        # None for an empty row). Same live-ticking pattern as
        # _share_expiry_data above, just counting UP (time since)
        # instead of counting down (time until).
        self._payout_found_data = [None, None, None, None, None]

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        # -- Live event listener -------------------------------------
        # Runs on its own background thread (see event_listener.py's
        # docstring for why). new_event.connect() below is what makes
        # _on_p2pool_event() get called safely on OUR thread (the
        # main/GUI thread) every time the background thread emits,
        # even though the two run independently.
        self.event_listener = P2PoolEventListener(network)
        self.event_listener.new_event.connect(self._on_p2pool_event)
        self.event_listener.start()

        # Kick off the very first data load immediately, rather than
        # waiting 300 seconds for the first numbers to appear.
        self.refresh_data()

    # ------------------------------------------------------------
    # UI construction (same shell as GUI Test, titles now dynamic)
    # ------------------------------------------------------------
    def _build_top_bar(self):
        top_bar = QHBoxLayout()

        logo_label = QLabel()
        if os.path.exists(LOGO_PATH):
            pixmap = QPixmap(LOGO_PATH).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(rounded_pixmap(pixmap, radius=8))
        top_bar.addWidget(logo_label)

        title_label = QLabel(f"P2Pool Observer Dashboard — {_NETWORK_LABELS[self.network]}")
        title_label.setProperty("heading", "true")
        top_bar.addWidget(title_label)
        top_bar.addStretch(1)

        refresh_column = QVBoxLayout()
        refresh_column.setSpacing(2)

        self.next_refresh_label = QLabel("")
        self.next_refresh_label.setProperty("subtext", "true")
        self.next_refresh_label.setAlignment(Qt.AlignCenter)
        refresh_column.addWidget(self.next_refresh_label)

        self.refresh_button = QPushButton("Refresh Now")
        self.refresh_button.setToolTip(
            f"Manually re-fetches data early. Limited to once every "
            f"{REFRESH_COOLDOWN_SECONDS} seconds to avoid hammering the API."
        )
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        refresh_column.addWidget(self.refresh_button)

        self.cooldown_label = QLabel("")
        self.cooldown_label.setProperty("subtext", "true")
        self.cooldown_label.setAlignment(Qt.AlignCenter)
        refresh_column.addWidget(self.cooldown_label)

        top_bar.addLayout(refresh_column)

        self.help_button = QPushButton("Help")
        self.help_button.clicked.connect(self._on_help_clicked)
        top_bar.addWidget(self.help_button)

        return top_bar

    def _build_body(self):
        body = QHBoxLayout()
        body.addWidget(self._build_network_panel(), stretch=1)
        body.addWidget(self._build_wallet_panel(), stretch=1)
        return body

    def _build_converter_panel(self):
        group = QGroupBox("XMR Price Converter")
        row = QHBoxLayout(group)

        amount_label = QLabel("Amount (XMR):")
        row.addWidget(amount_label)

        self.converter_amount_field = QLineEdit("1")
        self.converter_amount_field.setFixedWidth(120)
        # Restricts typed characters to digits and a single decimal
        # point -- Qt simply refuses any keystroke that doesn't match
        # this pattern, so there's nothing extra we need to check
        # afterward. This directly satisfies "disregard anything but
        # numbers or a period."
        validator = QRegularExpressionValidator(QRegularExpression(r"^[0-9]*\.?[0-9]*$"))
        self.converter_amount_field.setValidator(validator)
        self.converter_amount_field.textChanged.connect(self._update_converter_result)
        row.addWidget(self.converter_amount_field)

        equals_label = QLabel("=")
        row.addWidget(equals_label)

        self.converter_result_label = QLabel("--")
        self.converter_result_label.setProperty("heading", "true")
        row.addWidget(self.converter_result_label)

        row.addStretch(1)

        currency_label = QLabel("Currency:")
        row.addWidget(currency_label)

        self.currency_combo = QComboBox()
        self.currency_combo.addItem("USD", userData="usd")
        self.currency_combo.addItem("GBP", userData="gbp")
        self.currency_combo.addItem("EUR", userData="eur")
        preferred = self.config.get_preferred_currency()
        index = self.currency_combo.findData(preferred)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)
        self.currency_combo.currentIndexChanged.connect(self._on_currency_changed)
        row.addWidget(self.currency_combo)

        # Holds the latest fetched prices, e.g. {"usd": 158.3, ...}.
        # None until the first successful price fetch completes.
        self._xmr_prices = None

        return group

    def _on_currency_changed(self, index):
        currency_code = self.currency_combo.currentData()
        self.config.set_preferred_currency(currency_code)
        self.config.save()
        self._update_converter_result()

    def _update_converter_result(self):
        """
        Recalculates the converted amount shown next to "=". Called
        whenever the amount field changes, the currency changes, or
        fresh prices arrive from a refresh.
        """
        if not self._xmr_prices:
            self.converter_result_label.setText("--")
            return

        currency_code = self.currency_combo.currentData()
        price = self._xmr_prices.get(currency_code)
        if price is None:
            self.converter_result_label.setText("--")
            return

        amount_text = self.converter_amount_field.text()
        try:
            # An empty field, or just "." typed so far, isn't a valid
            # number yet -- treat it as 0 rather than crashing on
            # float("").
            amount = float(amount_text) if amount_text not in ("", ".") else 0.0
        except ValueError:
            amount = 0.0

        converted = amount * price
        symbol = {"usd": "$", "gbp": "£", "eur": "€"}.get(currency_code, "")
        self.converter_result_label.setText(f"{symbol}{converted:,.2f}")

    def _build_network_panel(self):
        group = QGroupBox(f"P2Pool Network: {_NETWORK_LABELS[self.network]}")
        layout = QVBoxLayout(group)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        self.stat_height = make_stat_row(grid, 0, "P2Pool Height",
            "The current block height of this P2Pool sidechain.")
        self.stat_hashrate = make_stat_row(grid, 1, "P2Pool Hashrate",
            "Combined mining power of everyone on this P2Pool instance right now.")
        self.stat_last_block = make_stat_row(grid, 2, "Time Since Last Block Found",
            "How long ago P2Pool found a Monero block. Exact date/time shown below.")
        self.stat_avg_frequency = make_stat_row(grid, 3, "Average Block Frequency",
            "Average time between blocks found, based on the last few found.")
        self.stat_window_miners = make_stat_row(grid, 4, "Window Miners",
            "Number of distinct miners with shares in the current payout window.")
        self.stat_payout_per_share = make_stat_row(grid, 5, "Average Share Value",
            "The pool-wide AVERAGE reward per share right now (total expected "
            "reward divided by share count). A genuine average, mathematically "
            "identical to weighting by each share's real difficulty and summing -- "
            "unlike a per-WALLET estimate, an average across the whole pool doesn't "
            "need individual share weights to be correct. Any one share can still "
            "be worth more or less than this, depending on its own difficulty.")
        layout.addLayout(grid)

        self.last_block_time_label = QLabel("")
        self.last_block_time_label.setProperty("subtext", "true")
        layout.addWidget(self.last_block_time_label)

        self.hashrate_graph = HashrateGraphWidget()
        layout.addWidget(self.hashrate_graph)

        recent_caption = QLabel("Last 3 Blocks Found")
        recent_caption.setProperty("subtext", "true")
        layout.addWidget(recent_caption)
        self.recent_blocks_table = make_table(["Date / Time", "Reward (XMR)"], 3)
        layout.addWidget(self.recent_blocks_table)

        layout.addStretch(1)
        return group

    def _build_wallet_panel(self):
        title = "Wallet: none selected" if not self.wallet_address else \
            f"Wallet: {self.wallet_address[:10]}...{self.wallet_address[-6:]}"
        self.wallet_group = QGroupBox(title)
        layout = QVBoxLayout(self.wallet_group)

        self.wallet_not_found_label = QLabel(
            "No entry found for this wallet on P2Pool yet.\n"
            "New wallets can take hours, or even days, to appear, depending on luck."
        )
        self.wallet_not_found_label.setWordWrap(True)
        self.wallet_not_found_label.setProperty("subtext", "true")
        self.wallet_not_found_label.setVisible(False)
        layout.addWidget(self.wallet_not_found_label)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.stat_wallet_last_share = make_stat_row(grid, 0, "Last Share Found",
            "Most recent time this wallet contributed a share to P2Pool.")
        self.stat_wallet_active_shares = make_stat_row(grid, 1, "Current Active Shares",
            "Shares from this wallet still counted in the active payout window.")
        self.stat_wallet_shares_today = make_stat_row(grid, 2, "Shares (Last 24h)",
            "Shares this wallet has found in roughly the last 24 hours.")
        self.stat_wallet_est_reward = make_stat_row(grid, 3, "Estimated Window Reward",
            "Estimate of this wallet's payout if a block were found right now, based "
            "on this wallet's real PPLNS weight (share difficulty, with uncle "
            "adjustments) as a fraction of the whole window's weight -- the same "
            "method p2pool.observer itself uses. Still an estimate: both the window's "
            "contents and the block reward shift constantly.")
        self.stat_wallet_pool_share = make_stat_row(grid, 4, "Pool Share %",
            "This wallet's percentage of the current PPLNS window, by weight.")
        layout.addLayout(grid)

        share_age_caption = QLabel("Recent Share Age / Expiration")
        share_age_caption.setProperty("subtext", "true")
        layout.addWidget(share_age_caption)
        self.share_age_table = make_table(["Found", "Expires In"], 3)
        layout.addWidget(self.share_age_table)

        payouts_caption = QLabel("Recent Deposits")
        payouts_caption.setProperty("subtext", "true")
        layout.addWidget(payouts_caption)
        self.payout_table = make_table(["Amount (XMR)", "Age"], 5)
        layout.addWidget(self.payout_table)

        layout.addStretch(1)
        return self.wallet_group

    # ------------------------------------------------------------
    # Timer tick: drives both countdowns
    # ------------------------------------------------------------
    def _on_tick(self):
        if self._cooldown_seconds_left > 0:
            self._cooldown_seconds_left -= 1
            if self._cooldown_seconds_left <= 0:
                self.refresh_button.setEnabled(True)
                self.cooldown_label.setText("")
            else:
                self.cooldown_label.setText(f"Wait {self._cooldown_seconds_left}s")

        # Live stopwatch: ticks every second regardless of the
        # 300-second refresh cycle, so the number stays accurate
        # between refreshes instead of jumping in 300-second steps.
        if self._last_monero_block_ts is not None:
            elapsed = time.time() - self._last_monero_block_ts
            self.stat_last_block.setText(seconds_to_friendly_duration(elapsed))

        for row, expires_at in enumerate(self._share_expiry_data):
            if expires_at is None:
                continue
            remaining = expires_at - time.time()
            text = "Expired" if remaining <= 0 else seconds_to_friendly_duration(remaining)
            self.share_age_table.setItem(row, 1, QTableWidgetItem(text))

        for row, found_at in enumerate(self._payout_found_data):
            if found_at is None:
                continue
            age = time.time() - found_at
            self.payout_table.setItem(row, 1, QTableWidgetItem(seconds_to_friendly_duration(age)))

        self._seconds_until_price_refresh -= 1
        if self._seconds_until_price_refresh <= 0:
            self._seconds_until_price_refresh = PRICE_REFRESH_SECONDS
            self._refresh_price_only()
        minutes, seconds = divmod(self._seconds_until_price_refresh, 60)
        self.next_refresh_label.setText(f"Next price refresh: {minutes}:{seconds:02d}")

    def _engage_cooldown(self):
        """
        Starts the 30-second cooldown on the Refresh button. Shared
        by both refresh paths (manual click AND automatic 300-second
        refresh) so the button can't be spammed right after either
        kind of refresh, not just a manual one.
        """
        self._cooldown_seconds_left = REFRESH_COOLDOWN_SECONDS
        self.refresh_button.setEnabled(False)

    def _on_refresh_clicked(self):
        self.refresh_data()
        self._engage_cooldown()
        self._seconds_until_price_refresh = PRICE_REFRESH_SECONDS  # manual refresh resets that clock too

    def _on_help_clicked(self):
        # Reuse the same window instead of making a new one every
        # click -- if it's already open, just bring it to the front.
        if not hasattr(self, "_help_window") or self._help_window is None:
            self._help_window = HelpWindow(self)
        self._help_window.show()
        self._help_window.raise_()
        self._help_window.activateWindow()

    # ------------------------------------------------------------
    # Live events: called on the MAIN thread (Qt's queued-connection
    # mechanism guarantees this), so it's safe to touch widgets here
    # directly -- unlike code running inside P2PoolEventListener
    # itself, which must never touch the GUI.
    # ------------------------------------------------------------
    def _on_p2pool_event(self, event: dict):
        # apply_event() updates p2pool_state.py's local shadow of the
        # window (pure calculation, no network calls, see that file's
        # docstring for how). _render_all_from_state() then just
        # copies whatever the shadow currently says onto the widgets
        # -- the exact same rendering code refresh_data() uses after
        # a full REST bootstrap, so there's only one place that knows
        # how to draw these numbers, regardless of where they came
        # from.
        self.live_state.apply_event(event)

        if event.get("type") == "found_block":
            # A real Monero block just changed hands -- a rare,
            # meaningful checkpoint, and a reasonable moment to spend
            # one light pool_info call refreshing window_miner_count
            # and total_shares_in_window (the two numbers that only
            # update on a snapshot, not live -- see p2pool_state.py).
            # Failure here just leaves those two numbers at their
            # last known value; nothing else in the render depends on
            # this succeeding.
            self._refresh_network_totals_only()

        self._render_all_from_state()

    def _refresh_network_totals_only(self):
        try:
            pool_info = self.client.get_pool_info()
            self.live_state.refresh_network_totals(pool_info)
        except P2PoolAPIError:
            pass

    def closeEvent(self, event):
        # Qt calls this automatically when the window is closing.
        # Without this, the background thread would still be running
        # (mid-wait on a WebSocket message) when the app tries to
        # exit -- Qt prints a warning about a QThread being destroyed
        # while still running, and shutdown can hang or crash.
        # stop() asks the loop to exit; wait() blocks HERE (on the
        # main thread) briefly so we know it actually has before we
        # let the window finish closing.
        self.event_listener.stop()
        self.event_listener.wait(3000)
        super().closeEvent(event)

    # ------------------------------------------------------------
    # Bootstrap: the ONLY place that makes the full set of REST
    # calls now -- runs once at startup, and again if the user clicks
    # Refresh Now. Everything else redraws from live_state, which
    # this method seeds via bootstrap() before handing off to the
    # shared render methods below.
    # ------------------------------------------------------------
    def refresh_data(self):
        try:
            pool_info = self.client.get_pool_info()
            found_blocks = self.client.get_found_blocks(limit=3)
        except P2PoolAPIError as error:
            self.statusBar().showMessage(f"Network data fetch failed: {error}")
            return

        wide_shares = []
        payouts = []
        if self.wallet_address:
            try:
                self.client.get_miner_info(self.wallet_address)
                self.wallet_not_found_label.setVisible(False)
            except P2PoolAPIError:
                # This wallet has no record on P2Pool at all yet --
                # distinct from "zero shares right now," which is a
                # normal live_state reading, not an error.
                self.wallet_not_found_label.setVisible(True)

            # Wallet-scoped, so small regardless of how big the
            # network's overall window is -- this is the only
            # per-share REST call bootstrap makes now. See
            # p2pool_state.py's docstring for why the network-wide
            # window dump this used to also fetch got removed
            # entirely: pool_info already hands back the two numbers
            # it was for (window_miner_count, total_shares_in_window),
            # pre-counted, in one much lighter call.
            day_window = _APPROX_DAY_WINDOW.get(self.network, 8640)
            try:
                wide_shares = self.client.get_side_blocks_in_window(
                    self.wallet_address, window=day_window
                )
            except P2PoolAPIError:
                pass
            try:
                payouts = self.client.get_payouts(self.wallet_address, search_limit=5)
            except P2PoolAPIError:
                pass

        self.live_state.bootstrap(pool_info, found_blocks, wide_shares, payouts)
        self._render_all_from_state()
        self._refresh_price_only()

        now_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        self.statusBar().showMessage(f"Last Full Refresh: {now_str}")

    def _refresh_price_only(self):
        # Separate from P2Pool's own API entirely (CoinGecko, not
        # p2pool.observer) -- called both from refresh_data() above
        # and on its own PRICE_REFRESH_SECONDS timer, since this is
        # the one piece of the dashboard with no event feed to ride
        # along on.
        try:
            self._xmr_prices = get_xmr_prices()
            self._update_converter_result()
        except PriceAPIError:
            pass

    # ------------------------------------------------------------
    # Rendering: reads ONLY from live_state, never touches the
    # network. Called after a REST bootstrap above, AND after every
    # single live event -- same code path either way, so the numbers
    # can never disagree depending on which source produced them.
    # ------------------------------------------------------------
    def _render_all_from_state(self):
        self._render_network_panel()
        if self.wallet_address:
            self._render_wallet_panel()

    def _render_network_panel(self):
        state = self.live_state

        if state.height is not None:
            self.stat_height.setText(f"{state.height:,}")

        if state.difficulty is not None and state.block_time_seconds:
            hashrate_hs = calculate_hashrate(state.difficulty, state.block_time_seconds)
            self.stat_hashrate.setText(format_hashrate(hashrate_hs))
            self.hashrate_graph.add_point(hashrate_hs)

        self.stat_window_miners.setText(str(state.window_miner_count))

        found_blocks = state.recent_found_blocks
        if found_blocks:
            last_block_ts = found_blocks[0]["main_block"]["timestamp"]
            self._last_monero_block_ts = last_block_ts
            # Update the stopwatch immediately too, so it doesn't sit
            # on the old value for up to a second waiting for the
            # next tick.
            elapsed = time.time() - last_block_ts
            self.stat_last_block.setText(seconds_to_friendly_duration(elapsed))

            local_str = datetime.fromtimestamp(last_block_ts).strftime("%Y-%m-%d %I:%M:%S %p")
            self.last_block_time_label.setText(local_str)

            if len(found_blocks) >= 2:
                oldest_ts = found_blocks[-1]["main_block"]["timestamp"]
                newest_ts = found_blocks[0]["main_block"]["timestamp"]
                gap_count = len(found_blocks) - 1
                avg_seconds = (newest_ts - oldest_ts) / gap_count
                self.stat_avg_frequency.setText(seconds_to_friendly_duration(avg_seconds))
            else:
                self.stat_avg_frequency.setText("Not enough data")

            for row, block in enumerate(found_blocks[:3]):
                ts = block["main_block"]["timestamp"]
                reward_xmr = block["main_block"]["reward"] / 1e12
                local_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %I:%M %p")
                self.recent_blocks_table.setItem(row, 0, QTableWidgetItem(local_str))
                self.recent_blocks_table.setItem(row, 1, QTableWidgetItem(f"{reward_xmr:.6f}"))

            total_shares = state.total_shares_in_window
            if total_shares:
                # NOTE: this is a POOL-WIDE average, not a per-wallet
                # estimate -- and unlike the per-wallet stat above (see
                # wallet_estimated_window_reward_atomic in
                # p2pool_state.py), this one does NOT need to switch to
                # weight-based math. Checked algebraically: average
                # reward / share count is always identical to (average
                # reward / total weight) * (average weight per share),
                # regardless of how unevenly weight is spread across
                # shares -- that's just how averages work. Confirmed
                # against real debug data too: both methods produced
                # the exact same result to the last decimal place.
                # Only the wording changed here (see the tooltip
                # above), since "what one share is worth" reads like a
                # promise about any single share, when it's really an
                # average one specific share can land above or below.
                avg_reward_xmr = sum(b["main_block"]["reward"] for b in found_blocks) / len(found_blocks) / 1e12
                payout_per_share = avg_reward_xmr / total_shares
                self.stat_payout_per_share.setText(f"{payout_per_share:.8f} XMR")

    def _render_wallet_panel(self):
        state = self.live_state

        last_share_ts = state.wallet_last_share_ts
        if last_share_ts:
            local_str = datetime.fromtimestamp(last_share_ts).strftime("%Y-%m-%d %I:%M:%S %p")
            self.stat_wallet_last_share.setText(local_str)

        self.stat_wallet_active_shares.setText(str(state.wallet_active_shares))
        self.stat_wallet_shares_today.setText(str(state.wallet_shares_last_24h))

        share_age_rows = state.wallet_share_age_rows(3)
        for row in range(3):
            if row < len(share_age_rows):
                found_ts, expires_at = share_age_rows[row]
                remaining_seconds = expires_at - time.time()
                found_str = datetime.fromtimestamp(found_ts).strftime("%m-%d %I:%M %p")
                expires_str = "Expired" if remaining_seconds <= 0 else seconds_to_friendly_duration(remaining_seconds)
                self.share_age_table.setItem(row, 0, QTableWidgetItem(found_str))
                self.share_age_table.setItem(row, 1, QTableWidgetItem(expires_str))
                self._share_expiry_data[row] = expires_at
            else:
                self.share_age_table.setItem(row, 0, QTableWidgetItem("--"))
                self.share_age_table.setItem(row, 1, QTableWidgetItem("--"))
                self._share_expiry_data[row] = None

        payouts = state.wallet_recent_payouts
        for row in range(5):
            if row < len(payouts):
                payout = payouts[row]
                amount_xmr = payout["coinbase_reward"] / 1e12
                found_ts = payout["timestamp"]
                age_str = seconds_to_friendly_duration(time.time() - found_ts)
                self.payout_table.setItem(row, 0, QTableWidgetItem(f"{amount_xmr:.6f}"))
                self.payout_table.setItem(row, 1, QTableWidgetItem(age_str))
                self._payout_found_data[row] = found_ts
            else:
                self.payout_table.setItem(row, 0, QTableWidgetItem("--"))
                self.payout_table.setItem(row, 1, QTableWidgetItem("--"))
                self._payout_found_data[row] = None

        # Weight-based estimate -- replaces the old share-COUNT-based
        # version (wallet_active_shares / total_shares_in_window),
        # which treated every share as worth the same amount. It
        # isn't: a share's difficulty varies, and uncle shares are
        # worth less than a regular share. See p2pool_state.py's
        # _share_weight() for exactly how that's accounted for.
        #
        # wallet_estimated_window_reward_atomic already does the full
        # calculation (this wallet's weight / the window's total
        # weight, times the current base block reward) -- all we do
        # here is convert its atomic-unit result into XMR for
        # display, same as every other reward number on this screen.
        estimated_reward = atomic_to_xmr(state.wallet_estimated_window_reward_atomic)
        self.stat_wallet_est_reward.setText(f"{estimated_reward:.6f} XMR")
        self.stat_wallet_pool_share.setText(f"{state.wallet_pool_share_percent:.3f}%")

