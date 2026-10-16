"""Trackpad gestures for the desktop console.

Two-finger scrolling: Tk 9 reports trackpad scrolling as <TouchpadScroll> instead of
<MouseWheel>, and CustomTkinter's scrollable frames only handle <MouseWheel>. The
handler here moves the scrollable frame under the pointer by the reported pixels.
Tk 8.6 sends <MouseWheel> for trackpads, which the frames already handle.

Pinch to zoom on macOS: Tk does not deliver trackpad magnify events, so an optional
PyObjC event monitor (requirements-mac.txt) records the pinch and the Tk loop applies
it to the map. The monitor only stores a number; it never calls Tk, because it runs
inside Tk's own event processing.
"""
from __future__ import annotations

import sys
import time
import tkinter as tk

import customtkinter as ctk

NS_EVENT_MASK_MAGNIFY = 1 << 30  # NSEventMaskMagnify


def scroll_deltas(widget, delta: int) -> tuple[float, float]:
    """(dx, dy) in pixels from a Tk 9 <TouchpadScroll> delta."""
    try:
        dx, dy = widget.tk.splitlist(widget.tk.call("tk::PreciseScrollDeltas", delta))
        return float(dx), float(dy)
    except (tk.TclError, ValueError):
        # Tk packs signed 16-bit X and Y distances into one integer.
        dx, dy = (delta >> 16) & 0xffff, delta & 0xffff
        return float(dx - 0x10000 if dx >= 0x8000 else dx), float(dy - 0x10000 if dy >= 0x8000 else dy)


def scroll_frame(frame, pixels: float) -> bool:
    """Move a CTkScrollableFrame's view down by pixels (negative moves up)."""
    canvas = getattr(frame, "_parent_canvas", None)
    if canvas is None:
        return False
    content, view = frame.winfo_reqheight(), canvas.winfo_height()
    if content <= view:
        return True
    top = max(0.0, min(content - view, canvas.canvasy(0) + pixels))
    canvas.yview_moveto(top / content)
    return True


def scrollable_under(widget):
    """The CTkScrollableFrame containing a widget, including its own empty canvas."""
    while widget is not None:
        if isinstance(widget, ctk.CTkScrollableFrame):
            return widget
        if isinstance(widget, tk.Canvas):
            for child in widget.winfo_children():
                if isinstance(child, ctk.CTkScrollableFrame):
                    return child
        widget = getattr(widget, "master", None)
    return None


def install_touchpad_scroll(root) -> bool:
    """Scroll CustomTkinter lists with two fingers on Tk 9; returns False on Tk 8.6."""
    def scroll(event):
        widget = event.widget
        if isinstance(widget, str):
            try:
                widget = root.nametowidget(widget)
            except KeyError:
                return None
        frame = scrollable_under(widget)
        if frame is None:
            return None
        _dx, dy = scroll_deltas(root, event.delta)
        # Same direction as Tk's own text widget: the view moves by -dy pixels.
        return "break" if dy and scroll_frame(frame, -dy) else None

    try:
        root.bind_all("<TouchpadScroll>", scroll, add="+")
    except tk.TclError:
        return False
    return True


def speed_up_scrollbars() -> None:
    """Stop CustomTkinter scrollbars from forcing a full window redraw on every scroll step.

    CTkScrollbar._draw ends with update_idletasks(), so each step of a long list redrew every
    pending widget in the window at once (about 56 ms a step on the incident panel, under
    20 frames a second). Tk redraws the scrollbar at the next idle moment anyway.
    """
    original = ctk.CTkScrollbar.__init__
    if getattr(original, "argus_fast", False):
        return

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self._canvas.update_idletasks = lambda: None

    init.argus_fast = True
    ctk.CTkScrollbar.__init__ = init


class PinchZoom:
    """Apply macOS trackpad pinches to the map, one zoom level per STEP of magnification."""
    STEP = 0.2

    def __init__(self, app):
        self.app = app
        self.pending = 0.0
        self.total = 0.0
        self.last = 0.0
        self.monitor = None
        self.timer = None
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSEvent
        except ImportError:
            return

        def record(event):
            try:
                self.pending += float(event.magnification())
            except Exception:  # Never disturb event delivery.
                pass
            return event

        try:
            self.monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NS_EVENT_MASK_MAGNIFY, record)
        except Exception:
            self.monitor = None
            return
        self.ns_event = NSEvent
        self.timer = app.root.after(40, self.poll)

    @property
    def available(self) -> bool:
        return self.monitor is not None

    def poll(self) -> None:
        self.timer = None
        value, self.pending = self.pending, 0.0
        try:
            self.apply(value)
        finally:
            self.timer = self.app.root.after(40, self.poll)

    def apply(self, magnification: float) -> None:
        """Zoom the map at the pointer once the pinch passes a step; ignore pinches elsewhere."""
        now = time.monotonic()
        if not magnification:
            if now - self.last > 0.4:
                self.total = 0.0
            return
        self.last = now
        self.total += magnification
        steps = max(-2, min(2, int(self.total / self.STEP)))
        if not steps:
            return
        self.total -= steps * self.STEP
        app = self.app
        x, y = app.root.winfo_pointerxy()
        if app.root.winfo_containing(x, y) is not app.map:
            return
        if hasattr(app, "ais_tracker"):
            app.ais_tracker.follow.set(False)
        app._zoom_at(steps, x - app.map.winfo_rootx(), y - app.map.winfo_rooty())

    def close(self) -> None:
        if self.timer:
            try:
                self.app.root.after_cancel(self.timer)
            except tk.TclError:
                pass
            self.timer = None
        if self.monitor is not None:
            try:
                self.ns_event.removeMonitor_(self.monitor)
            except Exception:
                pass
            self.monitor = None
