"""
main.py
--------
The actual program entry point. Deliberately small: it just shows
the startup dialog, and if the user continues, opens the main
window with their choices. All the real logic lives in the other
files -- this one just wires them together in order.

RUN THIS ONE to start the whole dashboard:
    python3 main.py
"""

import sys

from PySide6.QtWidgets import QApplication

import theme
from config import ConfigManager
from startup_dialog import StartupDialog
from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)

    config = ConfigManager("cache/config.json")
    config.load()

    startup = StartupDialog(config)
    startup.exec()

    if not startup.was_accepted:
        # User closed the startup dialog without continuing --
        # exit quietly instead of opening a blank main window.
        sys.exit(0)

    window = MainWindow(
        network=startup.selected_network,
        wallet_address=startup.selected_wallet_address,
        config=config,
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
