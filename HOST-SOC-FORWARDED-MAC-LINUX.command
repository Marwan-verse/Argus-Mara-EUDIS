#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || exit 1
fi
.venv/bin/python -m pip install -r requirements.txt || exit 1
exec .venv/bin/python scripts/start_soc_forwarded.py "$@"
