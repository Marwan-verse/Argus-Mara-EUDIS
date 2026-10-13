#!/bin/bash
# Double-click this file in Finder: fetch the latest commits of this branch, then open the desktop app.
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

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then PY=python; fi
if [ ! -x .venv/bin/python ]; then
  echo "Setting up. First time only, about a minute..."
  if ! "$PY" -m venv .venv; then
    echo "Python 3.10 or newer with Tkinter is required: https://www.python.org/downloads/"
    finish 1
  fi
fi
if ! .venv/bin/python -c "import customtkinter, PIL" >/dev/null 2>&1; then
  echo "Installing the desktop UI packages..."
  if ! .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt; then
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

if ! .venv/bin/python run_gui.py; then
  echo "The app stopped with an error."
  finish 1
fi
