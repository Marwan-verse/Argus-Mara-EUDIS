"""Only the main thread may release Tk fonts, images and variables.

Tkinter frees a font, image or variable from its ``__del__``, which calls into Tcl. When the
garbage collector happens to run on a worker thread (the satellite status reader, a tile or
weather fetch), that call is handed to the main thread and the worker waits for an answer. If the
Tk interpreter that owned the object is already destroyed, or the main thread is itself waiting
for that worker, the answer never comes and the worker hangs for ever; at exit Python then waits
for the worker. CI on Windows with Python 3.11 hung exactly so after every test had passed
(thread stack: Font.__del__ inside desktop_satellite.read_watch).

With this guard a release attempted on another thread is skipped. The cost is a few bytes of Tcl
memory for an object that was already unreachable; an object released on the main thread is
freed as before.
"""
from __future__ import annotations

import threading
import tkinter
import tkinter.font

from PIL import ImageTk


def _guard(cls) -> None:
    original = cls.__del__
    if getattr(original, "argus_main_thread_only", False):
        return

    def release(self, _original=original):
        if threading.current_thread() is threading.main_thread():
            _original(self)

    release.argus_main_thread_only = True
    cls.__del__ = release


def guard_tk_finalizers() -> None:
    """Install the guard once; safe to call again."""
    for cls in (tkinter.font.Font, tkinter.Image, tkinter.Variable, ImageTk.PhotoImage):
        _guard(cls)
