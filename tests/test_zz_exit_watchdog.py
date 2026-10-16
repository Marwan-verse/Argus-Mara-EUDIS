"""Diagnostic: if the test process has not exited 60 s after the last test, print every thread's stack and stop.

Runs last (alphabetically). Temporary, to find what keeps Windows Python 3.11 from exiting.
"""
import faulthandler
import sys
import unittest


class ExitWatchdog(unittest.TestCase):
    def test_arm_exit_watchdog(self):
        faulthandler.dump_traceback_later(60, exit=True, file=sys.stderr)
