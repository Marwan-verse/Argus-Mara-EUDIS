#!/bin/bash
# Double-click this file. On Linux you may need: Right click -> Properties -> Allow executing.
cd "$(dirname "$0")/.." || exit 1

echo "=========================================="
echo "   ARGUS MARA - ship recorder"
echo "=========================================="
echo

finish() {
  echo
  read -r -p "Press Enter to close this window. "
  exit "${1:-0}"
}

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then PY=python; fi
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python is not installed on this computer."
  echo
  echo "  On a Mac: open Terminal and run    xcode-select --install"
  echo "  Or download it from               https://www.python.org/downloads/"
  echo
  echo "Then double-click this file again."
  finish 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Setting up. First time only, about a minute..."
  if ! "$PY" -m venv .venv; then
    echo
    echo "Could not set up Python in this folder."
    echo "On Debian or Ubuntu try:  sudo apt install python3-venv"
    finish 1
  fi
  .venv/bin/python -m pip install --quiet --disable-pip-version-check --upgrade pip
  if ! .venv/bin/python -m pip install --quiet --disable-pip-version-check -r recorder/requirements.txt; then
    echo
    echo "Could not download the two libraries it needs."
    echo "Check your internet connection and run this file again."
    finish 1
  fi
fi

echo
echo "LEAVE THIS WINDOW OPEN. That is all it needs."
echo "To stop: press Ctrl+C, or close the window."
echo

# caffeinate stops a Mac falling asleep while this runs
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i .venv/bin/python recorder/recorder.py
else
  .venv/bin/python recorder/recorder.py
fi

echo
echo "Recorder stopped."
finish 0
