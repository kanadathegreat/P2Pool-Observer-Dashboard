#!/bin/bash
#
# launch.sh
# ----------
# Double-click launcher for P2Pool Observer Dashboard.
#
# What this does, in order:
#   1. Moves into this script's own folder (so it works no matter
#      where it's double-clicked from -- desktop, app menu, etc)
#   2. Checks the virtual environment exists
#   3. Runs the program using that venv's own Python directly
#      (no "activate" needed for this -- see note below)
#   4. If anything fails, shows a proper popup error window instead
#      of just vanishing or leaving a mysterious terminal flash
#
# WHY THIS WON'T LEAVE ZOMBIE PROCESSES:
# This script runs main.py normally, in the FOREGROUND -- it just
# waits right here until the program closes, the same as if you'd
# typed the command yourself. Nothing gets sent to the background
# with "&", and nothing gets disowned from this shell. When you
# close the dashboard window, Python exits, this script continues
# past that line, and then the whole script exits too. There's
# nothing left running afterward, by construction, not by luck.

# This one line finds the folder this SCRIPT lives in (not the
# folder you happened to be in when you double-clicked it), and
# moves there. This is what makes the script location-independent --
# it never hardcodes a path like /home/kanada/Software/....
cd "$(dirname "$0")"

# We call the venv's OWN python3 binary directly by its full path,
# rather than "source venv/bin/activate" first. Both approaches work,
# but calling the binary directly is simpler in a script: "activate"
# is designed for a human typing commands afterward in the same
# terminal, and isn't really needed just to run one program and exit.
PYTHON_BIN="venv/bin/python3"

# --------------------------------------------------------------
# show_error: pops up a real error WINDOW, trying a few common
# tools in order until one is found. Falls back to plain terminal
# text only if none of them exist (unlikely on Mint, which ships
# zenity by default).
# --------------------------------------------------------------
show_error() {
    local message="$1"

    if command -v zenity &> /dev/null; then
        zenity --error --title="P2Pool Observer Dashboard" --text="$message" --width=400
    elif command -v kdialog &> /dev/null; then
        kdialog --error "$message" --title "P2Pool Observer Dashboard"
    elif command -v xmessage &> /dev/null; then
        xmessage -center "$message"
    else
        # Last resort: no GUI popup tool found at all. This still
        # prints somewhere, even if you double-clicked and there's
        # no visible terminal -- better than silently doing nothing.
        echo "P2Pool Observer Dashboard error: $message" >&2
    fi
}

# --- Check 1: does the virtual environment even exist? -----------
if [ ! -x "$PYTHON_BIN" ]; then
    show_error "The Python virtual environment wasn't found in this folder.

Open a terminal here and run:
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt

Then try launching again."
    exit 1
fi

# --- Check 2: run the actual program ------------------------------
# If main.py exits with any non-zero status (a crash, a missing
# dependency, etc), this "if" catches that and shows the popup
# instead of just closing silently.
if ! "$PYTHON_BIN" main.py; then
    show_error "P2Pool Observer Dashboard failed to start.

Try running it from a terminal in this folder for more detail:
  venv/bin/python3 main.py"
    exit 1
fi

exit 0
