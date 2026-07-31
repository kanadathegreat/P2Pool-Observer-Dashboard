"""
main_window.py
----------------
The real dashboard window. Same visual shell as GUI Test's main.py,
now wired to actual live data via api_client.py, with a working
300-second auto-refresh and 30-second manual cooldown.
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
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, "assets", "logo.jpeg")

REFRESH_COOLDOWN_SECONDS = 30
AUTO_REFRESH_SECONDS = 300

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
        # cooldown + next auto-refresh), since they're both just "a
        # number that ticks down once a second." A separate timer per
        # countdown would do the same job with more moving parts.
        self._cooldown_seconds_left = 0
        self._seconds_until_auto_refresh = AUTO_REFRESH_SECONDS
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
        group = QGroupBox(f"P2Pool Network — {_NETWORK_LABELS[self.network]}")
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
        self.stat_payout_per_share = make_stat_row(grid, 5, "Current Payout Per Share",
            "Rough estimate of what one share is worth right now, in XMR.")
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
        title = "Wallet — none selected" if not self.wallet_address else \
            f"Wallet — {self.wallet_address[:10]}...{self.wallet_address[-6:]}"
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
            "Rough estimate of this wallet's payout if a block were found right now. "
            "Approximate: based on share COUNT, not actual PPLNS weighting.")
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

        self._seconds_until_auto_refresh -= 1
        if self._seconds_until_auto_refresh <= 0:
            self._seconds_until_auto_refresh = AUTO_REFRESH_SECONDS
            self.refresh_data()
            self._engage_cooldown()
        minutes, seconds = divmod(self._seconds_until_auto_refresh, 60)
        self.next_refresh_label.setText(f"Next auto-refresh: {minutes}:{seconds:02d}")

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
        self._seconds_until_auto_refresh = AUTO_REFRESH_SECONDS  # manual refresh resets the auto clock too

    def _on_help_clicked(self):
        # Reuse the same window instead of making a new one every
        # click -- if it's already open, just bring it to the front.
        if not hasattr(self, "_help_window") or self._help_window is None:
            self._help_window = HelpWindow(self)
        self._help_window.show()
        self._help_window.raise_()
        self._help_window.activateWindow()

    # ------------------------------------------------------------
    # The actual data fetch + UI update
    # ------------------------------------------------------------
    def refresh_data(self):
        try:
            pool_info = self.client.get_pool_info()
            found_blocks = self.client.get_found_blocks(limit=3)
        except P2PoolAPIError as error:
            self.statusBar().showMessage(f"Network data fetch failed: {error}")
            return

        self._update_network_panel(pool_info, found_blocks)

        if self.wallet_address:
            self._update_wallet_panel(pool_info, found_blocks)

        # Price fetch is separate from P2Pool's own API (CoinGecko,
        # not p2pool.observer), so a failure here shouldn't cancel
        # the rest of an otherwise-successful refresh -- just leave
        # the converter showing its last known value.
        try:
            self._xmr_prices = get_xmr_prices()
            self._update_converter_result()
        except PriceAPIError:
            pass

        now_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        self.statusBar().showMessage(f"Last updated: {now_str}")

    def _update_network_panel(self, pool_info, found_blocks):
        side = pool_info["sidechain"]
        difficulty = side["difficulty"]
        block_time = side["block_time"]
        height = side["height"]
        window_miners = side["window"]["miners"]
        window_size = side["window_size"]

        hashrate_hs = calculate_hashrate(difficulty, block_time)
        self.stat_height.setText(f"{height:,}")
        self.stat_hashrate.setText(format_hashrate(hashrate_hs))
        self.stat_window_miners.setText(str(window_miners))
        self.hashrate_graph.add_point(hashrate_hs)

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

            # Average frequency: time span across the found blocks we
            # have, divided by the number of gaps between them. Needs
            # at least 2 blocks to compute a gap at all.
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

        # Payout per share needs total shares in the window -- one
        # more call, but only made once per refresh (every 300s by
        # default), which is a light cost for a real number instead
        # of a placeholder.
        try:
            all_window_shares = self.client.get_all_side_blocks_in_window()
            total_shares = len(all_window_shares)
            if total_shares and found_blocks:
                avg_reward_xmr = sum(b["main_block"]["reward"] for b in found_blocks) / len(found_blocks) / 1e12
                payout_per_share = avg_reward_xmr / total_shares
                self.stat_payout_per_share.setText(f"{payout_per_share:.8f} XMR")
        except P2PoolAPIError:
            # Non-critical field -- if this one call fails, leave it
            # as "--" rather than failing the whole refresh over it.
            pass

    def _update_wallet_panel(self, pool_info, found_blocks):
        side = pool_info["sidechain"]
        block_time = side["block_time"]
        window_size = side["window_size"]
        # A share stays in the PPLNS payout window for exactly this
        # many seconds after being found -- confirmed against real
        # data: for Mini, window_size (2160) * block_time (10) works
        # out to exactly 21,600 seconds, i.e. 6 hours.
        window_duration_seconds = window_size * block_time

        try:
            miner_info = self.client.get_miner_info(self.wallet_address)
        except P2PoolAPIError:
            self.wallet_not_found_label.setVisible(True)
            return

        self.wallet_not_found_label.setVisible(False)

        last_share_ts = miner_info.get("last_share_timestamp")
        if last_share_ts:
            local_str = datetime.fromtimestamp(last_share_ts).strftime("%Y-%m-%d %I:%M:%S %p")
            self.stat_wallet_last_share.setText(local_str)

        # "Current Active Shares" -- the API's own live-window count,
        # authoritative for this number specifically.
        try:
            window_shares = self.client.get_side_blocks_in_window(self.wallet_address)
        except P2PoolAPIError:
            window_shares = []
        self.stat_wallet_active_shares.setText(str(len(window_shares)))

        # One wider fetch, reused for both "shares in last 24h" AND
        # the age/expiration table below -- a share that's already
        # expired won't appear in the live-window fetch above at all,
        # so we need this separate, wider lookback to find and show
        # it as "Expired" rather than have it just vanish.
        try:
            day_window = _APPROX_DAY_WINDOW.get(self.network, 8640)
            wide_shares = self.client.get_side_blocks_in_window(self.wallet_address, window=day_window)
        except P2PoolAPIError:
            wide_shares = []

        cutoff = time.time() - 86400
        shares_today = [s for s in wide_shares if s.get("timestamp", 0) >= cutoff]
        self.stat_wallet_shares_today.setText(str(len(shares_today)))

        # Share age / expiration table -- the 3 most recent shares,
        # shown whether still active or already expired. wide_shares
        # comes back newest-first (matches found_blocks' ordering,
        # confirmed against the API docs' example responses).
        for row in range(3):
            if row < len(wide_shares):
                share = wide_shares[row]
                found_ts = share["timestamp"]
                expires_at = found_ts + window_duration_seconds
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

        # Recent Deposits: actual Monero received by this wallet from
        # blocks P2Pool has found. Non-critical -- if this call fails
        # (or the wallet just doesn't have 5 payouts yet), we fall
        # back to "--" per row rather than failing the whole refresh.
        try:
            payouts = self.client.get_payouts(self.wallet_address, search_limit=5)
        except P2PoolAPIError:
            payouts = []

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

        # Estimated window reward: wallet's share COUNT divided by
        # total shares in the window, times the average recent block
        # reward. This is an approximation -- real PPLNS payouts are
        # weighted by share difficulty, not raw count. Labeled as an
        # estimate in the tooltip so it isn't mistaken for exact.
        try:
            all_window_shares = self.client.get_all_side_blocks_in_window()
            total_shares = len(all_window_shares)
            if total_shares and found_blocks:
                avg_reward_xmr = sum(b["main_block"]["reward"] for b in found_blocks) / len(found_blocks) / 1e12
                estimated_reward = (len(window_shares) / total_shares) * avg_reward_xmr
                self.stat_wallet_est_reward.setText(f"{estimated_reward:.6f} XMR")
        except P2PoolAPIError:
            pass
