"""A scrolling list drawn as items on one Tk canvas, for long panels that must scroll smoothly.

Why not a frame of widgets: on macOS (Tk 9) moving child windows makes Tk repaint the whole
window, map included. Scrolling the incident panel built from about 1,000 labels cost about
66 ms a frame, under 15 frames a second. Scrolling canvas items repaints only this canvas,
about 3 ms a frame.

Rows are plain objects with ``draw(view, y, width) -> height``. Each row's items carry the tag
``row:<key>``; clickable items carry ``click:<n>`` and are dispatched here. ``Field`` keeps the
text and colours of one part of a row, so code that used to configure labels keeps working and
a countdown update is one itemconfigure, not a redraw.
"""
from __future__ import annotations

import sys
import tkinter as tk

import customtkinter as ctk


class Field:
    """Text, colours and visibility of one part of a row, set like the Tk label it replaced."""

    def __init__(self, view=None, **options):
        self.view = view
        self.options = {"text": "", "fg": "", "bg": "", "font": None, **options}
        self.shown = True
        self.item: int | None = None

    def configure(self, **options) -> None:
        self.options.update(options)
        if self.item is None or self.view is None:
            return
        canvas = self.view.canvas
        try:
            kind = canvas.type(self.item)
        except tk.TclError:
            self.item = None
            return
        if kind == "text":
            update = {key: options[key] for key in ("text", "font") if key in options}
            if "fg" in options:
                update["fill"] = options["fg"]
        else:
            update = {"fill": options["bg"]} if "bg" in options else {}
        if update:
            canvas.itemconfigure(self.item, **update)

    config = configure

    def cget(self, key: str):
        return self.options.get(key, "")

    def pack(self, *_args, **_kwargs) -> None:
        self.shown = True

    def pack_forget(self) -> None:
        self.shown = False

    def winfo_manager(self) -> str:
        return "canvas" if self.shown else ""


class Link:
    """A clickable entry in a section: its full text (as a reader sees it) and what it does."""

    def __init__(self, text: str, command, kind: str = "entry", title: str = "", lines: str = "", action: str = ""):
        self.text, self.command, self.kind = text, command, kind
        self.title, self.lines, self.action = title, lines, action

    def cget(self, key: str):
        return self.text if key == "text" else ""

    def invoke(self):
        return self.command()


class CanvasList(tk.Frame):
    """The scrolling canvas, its scrollbar, hover tracking and click dispatch."""

    def __init__(self, master, background: str, scrollbar: str, scrollbar_hover: str):
        super().__init__(master, bg=background, highlightthickness=0)
        self.background = background
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0, yscrollincrement=1)
        self.scrollbar = ctk.CTkScrollbar(self, command=self.canvas.yview, width=12, fg_color=background,
                                          button_color=scrollbar, button_hover_color=scrollbar_hover)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.rows: list = []
        self.positions: dict[str, tuple[float, float]] = {}
        self.actions: dict[str, object] = {}
        self.hovered_row: str | None = None
        self.on_hover = None  # called with (row key or None)
        self.width = 0
        self.on_resize = None
        self.canvas.bind("<Configure>", self._resized)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda _event: self._set_hover(None))
        self.canvas.bind("<ButtonRelease-1>", self._click)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda _event: self.scroll_pixels(-48))
        self.canvas.bind("<Button-5>", lambda _event: self.scroll_pixels(48))

    # ----- drawing ------------------------------------------------------------------------
    def action(self, command) -> str:
        """A tag that runs command when an item carrying it is clicked."""
        tag = f"click:{len(self.actions)}"
        self.actions[tag] = command
        return tag

    def set_rows(self, rows) -> None:
        self.rows = list(rows)
        self.render()

    def render(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self.actions.clear()
        self.positions.clear()
        width = max(120, canvas.winfo_width())
        self.width = width
        y = 0.0
        for row in self.rows:
            height = row.draw(self, y, width)
            self.positions[row.key] = (y, height)
            y += height
        self._scrollregion(y)

    def redraw(self, key: str) -> None:
        """Draw one row again; rows below move if its height changed."""
        row = next((row for row in self.rows if row.key == key), None)
        if row is None or key not in self.positions:
            return
        y, old = self.positions[key]
        self.canvas.delete(f"row:{key}")
        height = row.draw(self, y, self.width or max(120, self.canvas.winfo_width()))
        self.positions[key] = (y, height)
        if height != old:
            below = False
            for other in self.rows:
                if below:
                    top, size = self.positions[other.key]
                    self.canvas.move(f"row:{other.key}", 0, height - old)
                    self.positions[other.key] = (top + height - old, size)
                below = below or other.key == key
            total = max((top + size for top, size in self.positions.values()), default=0)
            self._scrollregion(total)

    def _scrollregion(self, height: float) -> None:
        view = max(1, self.canvas.winfo_height())
        self.canvas.configure(scrollregion=(0, 0, self.width, max(height, view)))
        # Never leave empty space below the last row after the list shrinks.
        top = self.canvas.canvasy(0)
        if top > max(0.0, height - view):
            self.canvas.yview_moveto(max(0.0, height - view) / max(height, view))

    # ----- scrolling ----------------------------------------------------------------------
    def content_height(self) -> float:
        region = self.canvas.cget("scrollregion").split()
        return float(region[3]) if len(region) == 4 else 0.0

    def scroll_pixels(self, pixels: float) -> bool:
        content, view = self.content_height(), self.canvas.winfo_height()
        if content <= view:
            return True
        top = max(0.0, min(content - view, self.canvas.canvasy(0) + pixels))
        self.canvas.yview_moveto(top / content)
        return True

    def top(self) -> None:
        self.canvas.yview_moveto(0)

    def see(self, key: str, margin: float = 40) -> None:
        if key not in self.positions:
            return
        top, height = self.positions[key]
        first, view = self.canvas.canvasy(0), self.canvas.winfo_height()
        if top < first or top + height > first + view:
            content = max(1.0, self.content_height())
            self.canvas.yview_moveto(max(0.0, top - margin) / content)

    def _wheel(self, event) -> str:
        if event.state & 1:  # Shift marks horizontal scrolling on macOS
            return "break"
        delta = event.delta
        if abs(delta) >= 120:
            self.scroll_pixels(-delta / 120 * 48)  # Windows and Tk 9 mouse wheels: 120 per notch
        elif sys.platform == "darwin":
            self.scroll_pixels(-delta * 6)  # Tk 8.6 on macOS: small deltas from mice and trackpads
        else:
            self.scroll_pixels(-delta)
        return "break"

    # ----- pointer ------------------------------------------------------------------------
    def _row_under(self) -> str | None:
        for tag in self.canvas.gettags("current"):
            if tag.startswith("row:"):
                return tag[4:]
        return None

    def _set_hover(self, key: str | None) -> None:
        if key != self.hovered_row:
            self.hovered_row = key
            if self.on_hover:
                self.on_hover(key)

    def _motion(self, _event) -> None:
        self._set_hover(self._row_under())
        clickable = any(tag.startswith("click:") for tag in self.canvas.gettags("current"))
        self.canvas.configure(cursor="hand2" if clickable else "")

    def _click(self, _event) -> None:
        for tag in self.canvas.gettags("current"):
            if tag.startswith("click:") and tag in self.actions:
                self.actions[tag]()
                return

    def _resized(self, event) -> None:
        if event.width != self.width:
            self.width = event.width
            if self.on_resize:
                self.on_resize(event.width)
            else:
                self.render()
        else:
            self._scrollregion(self.content_height())
