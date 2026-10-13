#!/usr/bin/env python3
"""Open the desktop app with its alert panel scored through Brain's assembler.

A preview launcher: in this process only, the alert panel builds and updates its
items with ``argus.brain_board`` (``argus.assemble`` plus the small-vessel rule)
instead of ``argus.alert_board``. ``run_gui.py`` and ``desktop_alerts.py`` are
unchanged, and ``run_gui.py`` still opens the original panel.
"""

import desktop_alerts
import run_gui
from argus import brain_board

desktop_alerts.build_board = brain_board.build_board
desktop_alerts.update = brain_board.update

if __name__ == "__main__":
    raise SystemExit(run_gui.main())
