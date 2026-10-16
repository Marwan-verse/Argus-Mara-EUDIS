#!/bin/bash
# Double-click this file in Finder to compare fresh satellite images with AIS:
# update, install the satellite image readers once, connect the TensorX and team
# database keys once (hidden, saved in the Keychain), then open the app on
# Satellite analysis with Coast Watch running.
cd "$(dirname "$0")" || exit 1

finish() {
  echo
  read -r -p "Press Enter to close this window. "
  exit "${1:-0}"
}

if command -v git >/dev/null 2>&1; then
  echo "Fetching the latest version of this branch..."
  if ! git pull --ff-only; then
    echo "Update failed, so the version already on this computer will start."
  fi
else
  echo "Git is not installed, so the version already on this computer will start."
fi

SUITABLE="import sys, tkinter; raise SystemExit(sys.version_info < (3, 12))"
if [ ! -x .venv/bin/python ]; then
  PY=""
  for candidate in python3 python3.14 python3.13 python3.12 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "$SUITABLE" >/dev/null 2>&1; then
      PY=$candidate
      break
    fi
  done
  if [ -z "$PY" ] || ! { echo "Setting up. First time only, about a minute..."; "$PY" -m venv .venv; }; then
    echo "Python 3.12 or newer with Tkinter is required: https://www.python.org/downloads/"
    finish 1
  fi
fi
if ! .venv/bin/python -c "$SUITABLE" >/dev/null 2>&1; then
  echo "The satellite image readers need Python 3.12 or newer with Tkinter."
  echo "Install it from https://www.python.org/downloads/, delete the .venv folder and try again."
  finish 1
fi
if ! .venv/bin/python -c "import customtkinter, PIL, cryptography, keyring, numpy, rasterio, pyarrow, websockets" >/dev/null 2>&1; then
  echo "Installing the app and the satellite image readers. First time only, a few minutes..."
  if ! .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements-satellite.txt -r recorder/requirements.txt; then
    echo "Install failed. Check your internet connection and try again."
    finish 1
  fi
fi

if [ ! -f .venv/.pinch-checked ] && ! .venv/bin/python -c "import AppKit" >/dev/null 2>&1; then
  echo "Adding trackpad pinch-to-zoom (one time)..."
  if ! .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements-mac.txt; then
    echo "Pinch-to-zoom is unavailable; everything else works."
  fi
  touch .venv/.pinch-checked
fi

echo
if ! .venv/bin/python scripts/satellite_watch.py; then
  finish 1
fi
echo
echo "Opening the app. Coast Watch works while the app stays open; Stop in the app pauses it."
# Keep the Mac from idle sleep while the app waits for new images (closing the lid still sleeps).
KEEP_AWAKE=""
if command -v caffeinate >/dev/null 2>&1; then KEEP_AWAKE="caffeinate -i"; fi
if ! $KEEP_AWAKE .venv/bin/python run_gui.py --coast-watch; then
  echo "The app stopped with an error."
  finish 1
fi
