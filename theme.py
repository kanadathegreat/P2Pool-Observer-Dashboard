"""
theme.py
--------
All the color and style choices live here, separate from the window
logic in main.py. Reason: if you ever want to tweak a color (make the
orange more red, make panels lighter, etc), you only need to look in
ONE file, and you won't accidentally break window behavior while
doing it.

This uses Qt Style Sheets (QSS). QSS is basically CSS, but for
desktop apps instead of web pages. If you've seen CSS before
(color: red; background: black;) this will look familiar.
"""

# --- Color palette -----------------------------------------------
# Named colors as plain variables. This is the "single source of
# truth" -- every color in the stylesheet below is built from these,
# so changing one line here changes it everywhere it's used.

BG_DARKEST = "#161616"     # main window background, near-black
BG_PANEL = "#232323"       # panels / group boxes sit on this
BG_PANEL_LIGHT = "#2b2b2b" # slightly lighter panel elements (inputs, rows)
BORDER = "#3a3a3a"         # subtle borders between sections

TEXT_PRIMARY = "#e8e8e8"   # main readable text, off-white (not pure white,
                            # which is harsh on dark backgrounds)
TEXT_SECONDARY = "#9a9a9a" # dimmer text for labels/subtext

ORANGE = "#F26822"         # the Monero accent orange
ORANGE_HOVER = "#FF7B3A"   # slightly brighter, used when hovering a button
ORANGE_PRESSED = "#D4551A" # slightly darker, used when a button is clicked

DISABLED_BG = "#333333"    # buttons that are disabled (e.g. refresh on cooldown)
DISABLED_TEXT = "#6f6f6f"


# --- Fonts ----------------------------------------------------------
# Change these to try different fonts. A font name here only works if
# that font is actually installed on the machine running the app --
# if it isn't found, Qt silently falls back to a system default, it
# won't crash or error.
#
# Safe bets on Linux Mint / Ubuntu (usually pre-installed):
#   "Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans"
# If you install a font yourself (e.g. via Mint's font manager or
# `sudo apt install fonts-<name>`), you can put its name here too.
#
# FONT_FAMILY_BODY is used for regular text (stat labels, values).
# FONT_FAMILY_HEADING is used just for titles like "P2Pool Mini
# Dashboard" -- kept as a separate variable so you can pick something
# more distinctive for headings without changing all the body text.
FONT_FAMILY_BODY = "Ubuntu"
FONT_FAMILY_HEADING = "URW Gothic"


# --- The actual stylesheet ----------------------------------------
# This big string gets handed to the whole application at once
# (see main.py: app.setStyleSheet(...)). Qt then applies these rules
# to every matching widget automatically, the same way a CSS file
# applies to a whole website.
STYLESHEET = f"""
/* QMainWindow is the outer application window itself */
QMainWindow {{
    background-color: {BG_DARKEST};
}}

/* QDialog covers popup windows -- the startup dialog and help window */
QDialog {{
    background-color: {BG_DARKEST};
}}

/* The scrollable text area inside the Help window */
QTextEdit {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 10px;
    font-family: "{FONT_FAMILY_BODY}";
    font-size: 13px;
}}

/* Applies to plain text labels everywhere, unless overridden below */
QLabel {{
    color: {TEXT_PRIMARY};
    font-size: 13px;
    font-family: "{FONT_FAMILY_BODY}";
}}

/* A label with the "subtext" property set (we set this manually in
   code for smaller/dimmer text, like timestamps under a headline) */
QLabel[subtext="true"] {{
    color: {TEXT_SECONDARY};
    font-size: 11px;
    font-family: "{FONT_FAMILY_BODY}";
}}

/* A label with the "heading" property set -- used for section titles */
QLabel[heading="true"] {{
    color: {ORANGE};
    font-size: 20px;
    font-weight: bold;
    font-family: "{FONT_FAMILY_HEADING}";
}}

/* QGroupBox is the boxed "panel" widget we use to frame each section
   (Network Info, Wallet Info, etc) */
QGroupBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 12px;
    font-weight: bold;
    color: {TEXT_PRIMARY};
}}

/* The little title that sits on a QGroupBox's top border */
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 6px;
    color: {ORANGE};
    font-family: "{FONT_FAMILY_HEADING}";
}}

/* Normal push buttons (Refresh, Help, etc) */
QPushButton {{
    background-color: {ORANGE};
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
    font-family: "{FONT_FAMILY_BODY}";
}}
QPushButton:hover {{
    background-color: {ORANGE_HOVER};
}}
QPushButton:pressed {{
    background-color: {ORANGE_PRESSED};
}}
/* This is the state the Refresh button will be in during its
   30-second cooldown -- grayed out and unclickable */
QPushButton:disabled {{
    background-color: {DISABLED_BG};
    color: {DISABLED_TEXT};
}}

/* Dropdown menus (used later for the network / wallet selectors) */
QComboBox {{
    background-color: {BG_PANEL_LIGHT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}

/* Table widget (used later for share history, recent blocks, etc).
   Note: border-radius here rounds the OUTER frame of the table only.
   The individual cells inside stay sharp-edged, which is what was
   asked for -- rounded corners just on the container, not each cell. */
QTableWidget {{
    background-color: {BG_PANEL_LIGHT};
    color: {TEXT_PRIMARY};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-family: "{FONT_FAMILY_BODY}";
}}
QHeaderView::section {{
    background-color: {BG_PANEL};
    color: {ORANGE};
    padding: 4px;
    border: none;
    font-family: "{FONT_FAMILY_HEADING}";
}}

/* The bar along the very bottom of the window */
QStatusBar {{
    background-color: {BG_PANEL};
    color: {TEXT_SECONDARY};
}}
"""
