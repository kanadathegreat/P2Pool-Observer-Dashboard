"""
startup_dialog.py
-------------------
The window that appears when the program first opens: pick a
network (Normal / Mini / Nano), optionally enter or pick a wallet
address to track, and continue into the main dashboard.

This file DOES import config.py (it needs to load/save saved
settings), but it does NOT import api_client.py or main_window.py --
this dialog's job ends the moment the user clicks Continue. What
happens with their choice afterward is main.py's job, not this
file's. Keeping that boundary clean means this dialog can be tested
completely on its own, same as the last two files.
"""

import os

from PySide6.QtWidgets import (
    QApplication, QDialog, QLabel, QComboBox, QLineEdit, QCheckBox,
    QPushButton, QVBoxLayout, QHBoxLayout, QGroupBox, QMessageBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QIcon

import theme
from config import ConfigManager
from api_client import Network


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, "assets", "logo.jpeg")

# How each Network enum value should be LABELED on screen, and the
# reverse lookup to go from a label back to the enum. Kept as two
# small dicts rather than one, because "enum -> label" and
# "label -> enum" get used in different directions throughout this
# file, and a dict lookup each way is clearer than reversing one
# dict repeatedly.
_NETWORK_LABELS = {
    Network.NORMAL: "Normal",
    Network.MINI: "Mini",
    Network.NANO: "Nano",
}
_LABEL_TO_NETWORK = {label: network for network, label in _NETWORK_LABELS.items()}

# Placeholder text shown as the first item in the "recent wallets"
# dropdown, representing "I'm not picking a saved one."
_NO_RECENT_WALLET_TEXT = "-- Enter a new wallet below --"


def looks_like_monero_address(address: str) -> bool:
    """
    A loose sanity check, NOT a real validation. Real Monero
    addresses are 95 characters (or 106 for integrated addresses)
    and use a specific character set (base58). We don't need to be
    strict here -- P2Pool's own API will be the real judge of whether
    an address is valid once we query it. This function only exists
    to catch obvious typos (way too short, contains spaces, etc)
    before we even bother saving or querying it.
    """
    if not address:
        return False
    address = address.strip()
    # 90-110 comfortably covers standard, subaddress, and integrated
    # address lengths without hardcoding an exact number that might
    # be wrong for a format we didn't think of.
    return 90 <= len(address) <= 110 and " " not in address


class StartupDialog(QDialog):
    """
    After calling .exec() on an instance of this class, check
    .was_accepted to see if the user clicked Continue (True) or
    closed/cancelled the dialog (False). If accepted, read
    .selected_network and .selected_wallet_address for their choices.
    """

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config

        # These two are the actual "result" of this dialog -- what
        # main.py will read after the dialog closes.
        self.was_accepted = False
        self.selected_network = None       # a Network enum value
        self.selected_wallet_address = None  # a string, or None

        self.setWindowTitle("P2Pool Observer Dashboard — Startup")
        self.setMinimumWidth(480)
        if os.path.exists(LOGO_PATH):
            self.setWindowIcon(QIcon(LOGO_PATH))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_network_section())
        layout.addWidget(self._build_wallet_section())
        layout.addLayout(self._build_bottom_buttons())

        # Pre-fill from whatever was saved last time, so returning
        # users don't have to re-pick their usual network every run.
        self._load_saved_defaults()

    # ------------------------------------------------------------
    # Building the UI
    # ------------------------------------------------------------
    def _build_header(self):
        header = QHBoxLayout()

        logo_label = QLabel()
        if os.path.exists(LOGO_PATH):
            pixmap = QPixmap(LOGO_PATH).scaled(
                40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            logo_label.setPixmap(pixmap)
        header.addWidget(logo_label)

        title = QLabel("P2Pool Observer Dashboard")
        title.setProperty("heading", "true")
        header.addWidget(title)
        header.addStretch(1)

        return header

    def _build_network_section(self):
        group = QGroupBox("Network")
        layout = QVBoxLayout(group)

        self.network_combo = QComboBox()
        # Insert in a fixed, sensible order rather than however the
        # dict happens to iterate -- dict ordering in Python IS
        # reliable since 3.7, but relying on it here would still be
        # fragile if this dict's definition order ever changed for
        # an unrelated reason.
        for network in (Network.NORMAL, Network.MINI, Network.NANO):
            self.network_combo.addItem(_NETWORK_LABELS[network], userData=network)
        layout.addWidget(self.network_combo)

        # The warning from the original spec: picking the wrong
        # network means a wallet that's actually mining on Mini, say,
        # will show up as "not found" if Normal is selected instead.
        # This is styled with the "heading" property (bold + orange)
        # so it doesn't get missed the way a plain gray tip might be.
        warning = QLabel(
            "Tip: your wallet can only be tracked on the network it's "
            "actually mining on. If it shows no data, double check "
            "you've selected the right network here."
        )
        warning.setWordWrap(True)
        warning.setProperty("subtext", "true")
        layout.addWidget(warning)

        return group

    def _build_wallet_section(self):
        group = QGroupBox("Wallet (optional)")
        layout = QVBoxLayout(group)

        recent_label = QLabel("Recently tracked wallets:")
        recent_label.setProperty("subtext", "true")
        layout.addWidget(recent_label)

        self.recent_wallets_combo = QComboBox()
        self.recent_wallets_combo.currentIndexChanged.connect(
            self._on_recent_wallet_selected
        )
        layout.addWidget(self.recent_wallets_combo)
        self._refresh_recent_wallets_combo()

        self.wallet_address_field = QLineEdit()
        self.wallet_address_field.setPlaceholderText(
            "Paste your Monero wallet address here (optional)"
        )
        layout.addWidget(self.wallet_address_field)

        self.dont_remember_checkbox = QCheckBox(
            "Don't remember this wallet after this session"
        )
        self.dont_remember_checkbox.setToolTip(
            "If checked, this address won't be added to the "
            "'Recently tracked wallets' list for next time."
        )
        layout.addWidget(self.dont_remember_checkbox)

        return group

    def _build_bottom_buttons(self):
        row = QHBoxLayout()

        self.purge_button = QPushButton("Purge Saved Wallets")
        # A plain (non-orange) style for this button, since it's a
        # destructive, infrequently-used action -- it shouldn't visually
        # compete with "Continue" for attention. We override just this
        # one button's colors directly rather than adding a whole new
        # rule to theme.py for a single button.
        self.purge_button.setStyleSheet(
            f"QPushButton {{ background-color: {theme.BG_PANEL_LIGHT}; "
            f"color: {theme.TEXT_SECONDARY}; }} "
            f"QPushButton:hover {{ background-color: {theme.BORDER}; }}"
        )
        self.purge_button.clicked.connect(self._on_purge_clicked)
        row.addWidget(self.purge_button)

        row.addStretch(1)

        self.continue_button = QPushButton("Continue")
        self.continue_button.clicked.connect(self._on_continue_clicked)
        row.addWidget(self.continue_button)

        return row

    # ------------------------------------------------------------
    # Populating from saved config
    # ------------------------------------------------------------
    def _load_saved_defaults(self):
        last_network_name = self.config.get_last_network()
        if last_network_name:
            # get_last_network() returns a plain string like "mini"
            # (that's what's stored in the JSON file), so we convert
            # it back into a Network enum value to match the combo box.
            try:
                saved_network = Network(last_network_name)
                index = self.network_combo.findData(saved_network)
                if index >= 0:
                    self.network_combo.setCurrentIndex(index)
            except ValueError:
                # The saved value didn't match any known network --
                # just leave the combo box on its default. This could
                # happen if a config file got hand-edited or came
                # from a future version with a network we don't know.
                pass

    def _refresh_recent_wallets_combo(self):
        """
        Rebuilds the "recently tracked wallets" dropdown from
        whatever's currently saved in config, across ALL networks
        (since the spec asks for wallets AND their respective
        networks to be shown together here, not just for whichever
        network happens to be selected right now).
        """
        self.recent_wallets_combo.blockSignals(True)  # avoid triggering selection logic while rebuilding
        self.recent_wallets_combo.clear()
        self.recent_wallets_combo.addItem(_NO_RECENT_WALLET_TEXT, userData=None)

        for network in (Network.NORMAL, Network.MINI, Network.NANO):
            addresses = self.config.get_wallets_for_network(network.value)
            for address in addresses:
                label = f"[{_NETWORK_LABELS[network]}] {address[:10]}...{address[-6:]}"
                self.recent_wallets_combo.addItem(label, userData=(network, address))

        self.recent_wallets_combo.blockSignals(False)

    # ------------------------------------------------------------
    # Behavior
    # ------------------------------------------------------------
    def _on_recent_wallet_selected(self, index):
        """
        When the user picks a saved wallet from the dropdown, auto
        fill both the network selector and the address field to
        match it -- they can still edit the address afterward if
        they meant to pick a similar-but-different one.
        """
        data = self.recent_wallets_combo.itemData(index)
        if data is None:
            return  # they picked the "-- Enter a new wallet --" placeholder

        network, address = data
        network_index = self.network_combo.findData(network)
        if network_index >= 0:
            self.network_combo.setCurrentIndex(network_index)
        self.wallet_address_field.setText(address)

    def _on_purge_clicked(self):
        confirmation = QMessageBox.question(
            self,
            "Purge Saved Wallets",
            "This will permanently delete every saved wallet address "
            "on every network. This cannot be undone.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,  # "No" is the default, safer choice if they just hit Enter
        )

        if confirmation != QMessageBox.Yes:
            return

        self.config.clear_all_wallets()
        self.config.save()

        # Reflect the purge immediately in the UI, and clear whatever
        # address happened to be typed/selected, since it may have
        # just been deleted out from under it.
        self._refresh_recent_wallets_combo()
        self.wallet_address_field.clear()

    def _on_continue_clicked(self):
        network = self.network_combo.currentData()
        address = self.wallet_address_field.text().strip()

        if address and not looks_like_monero_address(address):
            proceed = QMessageBox.question(
                self,
                "Check Wallet Address",
                "That address doesn't look like a typical Monero "
                "address length. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if proceed != QMessageBox.Yes:
                return  # let them go back and fix it instead of closing the dialog

        # Save the network choice regardless of whether a wallet was
        # entered -- matches the spec: network selection gets cached
        # whenever a wallet ID is entered, and there's no harm in
        # always remembering the last network picked either way.
        self.config.set_last_network(network.value)

        if address and not self.dont_remember_checkbox.isChecked():
            self.config.add_wallet(network.value, address)

        self.config.save()

        self.selected_network = network
        self.selected_wallet_address = address if address else None
        self.was_accepted = True
        self.accept()  # closes the dialog, QDialog.exec() will return


# ------------------------------------------------------------------
# Standalone test: lets you open just this dialog by itself, without
# needing the rest of the application built yet.
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)

    config = ConfigManager("cache/config.json")
    config.load()

    dialog = StartupDialog(config)
    dialog.exec()

    if dialog.was_accepted:
        print(f"Network chosen: {dialog.selected_network}")
        print(f"Wallet chosen:  {dialog.selected_wallet_address}")
    else:
        print("Dialog was closed/cancelled without continuing.")
