"""
help_window.py
----------------
The window that opens when the Help button is clicked. Just a
scrollable, read-only text area -- no logic beyond displaying
help_content.py's text.
"""

import os

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
from PySide6.QtGui import QIcon

from help_content import HELP_TEXT

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, "assets", "logo.jpeg")


class HelpWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.resize(600, 500)
        if os.path.exists(LOGO_PATH):
            self.setWindowIcon(QIcon(LOGO_PATH))

        layout = QVBoxLayout(self)

        text_area = QTextEdit()
        text_area.setReadOnly(True)
        text_area.setHtml(HELP_TEXT)
        layout.addWidget(text_area)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)
