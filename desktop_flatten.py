"""Draw a Tk canvas's own items into one PIL image, so the map can move as a single picture.

While the operator drags or zooms, the map shows this one image and moves or scales it, instead
of moving and repainting about 2,500 canvas items on every frame. Lines, polygons, ovals,
rectangles, text and the map's tile images are reproduced from the live canvas (read in one Tcl
call, in stacking order), so what moves is what was on screen. When the motion ends the canvas is
redrawn normally and is crisp again.

Differences from Tk's own drawing are small and last only while the map moves: no anti-aliasing,
straight line ends, no arrowheads, and a close substitute for the font.
"""
from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

# One Tcl pass over the items; per type only the options the drawing needs.
_DUMP = r"""
namespace eval ::argusflat {}
proc ::argusflat::dump {c tag} {
    set out {}
    foreach i [$c find withtag $tag] {
        if {[$c itemcget $i -state] eq "hidden"} continue
        set t [$c type $i]
        switch -- $t {
            line {
                lappend out [list line [$c coords $i] [$c itemcget $i -fill] [$c itemcget $i -width] \
                    [$c itemcget $i -dash]]
            }
            polygon {
                lappend out [list polygon [$c coords $i] [$c itemcget $i -fill] [$c itemcget $i -outline] \
                    [$c itemcget $i -width]]
            }
            rectangle - oval {
                lappend out [list $t [$c coords $i] [$c itemcget $i -fill] [$c itemcget $i -outline] \
                    [$c itemcget $i -width] [$c itemcget $i -dash]]
            }
            text {
                lappend out [list text [$c bbox $i] [$c itemcget $i -text] [$c itemcget $i -fill] \
                    [$c itemcget $i -font] [$c itemcget $i -justify] [$c itemcget $i -angle]]
            }
            image {
                lappend out [list image [$c coords $i] [$c itemcget $i -image] [$c itemcget $i -anchor] \
                    [$c gettags $i]]
            }
        }
    }
    return $out
}
"""

# Font files close to what Tk draws. Tk itself picks the family; only its class (monospace or
# not) and weight matter here.
if sys.platform == "darwin":
    _SANS = [("/System/Library/Fonts/Helvetica.ttc", 0, 1)]
    _MONO = [("/System/Library/Fonts/Menlo.ttc", 0, 1)]
elif sys.platform == "win32":
    _FONTS = Path(r"C:\Windows\Fonts")
    _SANS = [(str(_FONTS / "segoeui.ttf"), 0, 0, str(_FONTS / "segoeuib.ttf")), (str(_FONTS / "arial.ttf"), 0, 0)]
    _MONO = [(str(_FONTS / "consola.ttf"), 0, 0, str(_FONTS / "consolab.ttf")), (str(_FONTS / "cour.ttf"), 0, 0)]
else:
    _SANS = [("DejaVuSans.ttf", 0, 0, "DejaVuSans-Bold.ttf")]
    _MONO = [("DejaVuSansMono.ttf", 0, 0, "DejaVuSansMono-Bold.ttf")]
_MONO_NAMES = ("mono", "menlo", "consolas", "courier", "monaco", "fixed")
_ANCHORS = {"nw": (0, 0), "n": (.5, 0), "ne": (1, 0), "w": (0, .5), "center": (.5, .5), "e": (1, .5),
            "sw": (0, 1), "s": (.5, 1), "se": (1, 1)}


class Flattener:
    """Renders one canvas; caches colours and fonts between calls."""

    def __init__(self, canvas, image_source=None):
        self.canvas = canvas
        self.tk = canvas.tk
        self.image_source = image_source  # (image name, tags) -> PIL image or None
        self.colours: dict[str, tuple | None] = {}
        self.offset = (0.0, 0.0)
        self.fonts: dict[str, ImageFont.ImageFont] = {}
        self.tk.eval(_DUMP)

    # ----- helpers --------------------------------------------------------------------------
    def colour(self, name: str):
        if not name:
            return None
        if name not in self.colours:
            try:
                red, green, blue = self.canvas.winfo_rgb(name)
                self.colours[name] = (red >> 8, green >> 8, blue >> 8)
            except Exception:
                self.colours[name] = None
        return self.colours[name]

    def numbers(self, value) -> list[float]:
        return [float(v) for v in self.tk.splitlist(value)]

    def font(self, spec):
        key = repr(spec)
        if key in self.fonts:
            return self.fonts[key]
        try:
            actual = self.tk.splitlist(self.tk.call("font", "actual", spec))
            options = dict(zip(actual[0::2], actual[1::2]))
            size = int(options.get("-size", 10))
            pixels = max(6, round(abs(size) if size < 0 else self.canvas.winfo_fpixels(f"{size}p")))
            family = str(options.get("-family", "")).lower()
            bold = str(options.get("-weight", "normal")) == "bold"
        except Exception:
            pixels, family, bold = 12, "", False
        candidates = _MONO if any(name in family for name in _MONO_NAMES) else _SANS
        result = None
        for entry in candidates:
            path, regular_index, bold_index = entry[0], entry[1], entry[2]
            bold_path = entry[3] if len(entry) > 3 else path
            try:
                result = ImageFont.truetype(bold_path if bold else path, pixels,
                                            index=bold_index if bold else regular_index)
                break
            except OSError:
                continue
        if result is None:
            try:
                result = ImageFont.load_default(pixels)
            except TypeError:  # Pillow before 10.1
                result = ImageFont.load_default()
        self.fonts[key] = result
        return result

    @staticmethod
    def width(value) -> int:
        try:
            return max(1, round(float(value)))
        except (TypeError, ValueError):
            return 1

    def dashes(self, value) -> list[int]:
        try:
            return [max(1, round(float(v))) for v in self.tk.splitlist(value)] if value else []
        except (TypeError, ValueError):
            return []

    @staticmethod
    def dashed(draw, points, pattern, fill, width) -> None:
        """A dashed polyline: Tk's on/off pattern walked along every segment."""
        index, left, on = 0, pattern[0], True
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** .5
            done = 0.0
            while done < length:
                step = min(left, length - done)
                if on:
                    start, end = done / length, (done + step) / length
                    draw.line([(x1 + (x2 - x1) * start, y1 + (y2 - y1) * start),
                               (x1 + (x2 - x1) * end, y1 + (y2 - y1) * end)], fill=fill, width=width)
                done += step
                left -= step
                if left <= 1e-9:
                    index = (index + 1) % len(pattern)
                    left, on = pattern[index], not on

    # ----- drawing --------------------------------------------------------------------------
    def render(self, tag: str, image: Image.Image, offset: tuple[float, float] = (0, 0)) -> Image.Image:
        """Draw the items carrying ``tag`` onto ``image``, canvas point (x, y) at pixel (x, y) + offset."""
        draw = ImageDraw.Draw(image)
        self.offset = offset
        for entry in self.tk.splitlist(self.tk.call("::argusflat::dump", str(self.canvas), tag)):
            fields = self.tk.splitlist(entry)
            try:
                self.item(image, draw, fields)
            except (ValueError, TypeError, OSError):
                continue  # One odd item must not stop the picture
        return image

    def points(self, value) -> list[float]:
        """Canvas coordinates shifted into the picture."""
        values = self.numbers(value)
        dx, dy = self.offset
        return [v + (dx if index % 2 == 0 else dy) for index, v in enumerate(values)]

    def item(self, image, draw, fields) -> None:
        kind = str(fields[0])
        if kind == "line":
            values = self.points(fields[1])
            fill = self.colour(str(fields[2]))
            if fill is None or len(values) < 4:
                return
            points = list(zip(values[0::2], values[1::2]))
            width = self.width(fields[3])
            pattern = self.dashes(fields[4])
            if pattern:
                self.dashed(draw, points, pattern, fill, width)
            else:
                draw.line(points, fill=fill, width=width, joint="curve" if width > 2 else None)
        elif kind == "polygon":
            values = self.points(fields[1])
            if len(values) < 6:
                return
            fill, outline = self.colour(str(fields[2])), self.colour(str(fields[3]))
            draw.polygon(list(zip(values[0::2], values[1::2])), fill=fill, outline=outline,
                         width=self.width(fields[4]) if outline else 1)
        elif kind in ("rectangle", "oval"):
            values = self.points(fields[1])
            if len(values) < 4:
                return
            x1, y1, x2, y2 = values[:4]
            box = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
            fill, outline = self.colour(str(fields[2])), self.colour(str(fields[3]))
            width = self.width(fields[4])
            shape = draw.rectangle if kind == "rectangle" else draw.ellipse
            if self.dashes(fields[5]) and outline and not fill:
                pattern = self.dashes(fields[5])
                if kind == "rectangle":
                    corners = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]), (box[0], box[1])]
                    self.dashed(draw, corners, pattern, outline, width)
                    return
            shape(box, fill=fill, outline=outline, width=width if outline else 0)
        elif kind == "text":
            value = fields[2]
            text = " ".join(str(part) for part in value) if isinstance(value, tuple) else str(value)
            bbox = self.points(fields[1])
            fill = self.colour(str(fields[3]))
            angle = float(fields[6] or 0) if len(fields) > 6 else 0.0
            if fill is None or not text or len(bbox) < 4 or abs(angle) > 0.5:
                return
            draw.multiline_text((bbox[0] + 1, bbox[1]), text, fill=fill, font=self.font(fields[4]),
                                align={"center": "center", "right": "right"}.get(str(fields[5]), "left"), spacing=2)
        elif kind == "image" and self.image_source is not None:
            values = self.points(fields[1])
            source = self.image_source(str(fields[2]), [str(tag) for tag in self.tk.splitlist(fields[4])])
            if source is None or len(values) < 2:
                return
            fx, fy = _ANCHORS.get(str(fields[3]), (.5, .5))
            at = (round(values[0] - fx * source.width), round(values[1] - fy * source.height))
            if source.mode == "RGBA":
                image.paste(source, at, source)
            else:
                image.paste(source.convert("RGB"), at)
