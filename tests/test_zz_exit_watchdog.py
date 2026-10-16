"""If the test process has not exited 120 s after the last test, print every thread's stack and stop.

Runs last (alphabetically). A hang at exit used to sit silently until CI's 10-minute limit
cancelled the job; this turns it into a failure with the stack that shows the cause (that is how
the worker-thread Tk release fixed in desktop_tk_safety was found).
"""
import faulthandler
import sys
import unittest


class ExitWatchdog(unittest.TestCase):
    def test_arm_exit_watchdog(self):
        faulthandler.dump_traceback_later(120, exit=True, file=sys.stderr)
