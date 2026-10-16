"""PDF of the analyst's vessel report, drawn with Pillow (no new package, no tkinter).

The first part is the analyst's text with its check status; the appendix is
built by code from the evidence pack, never by AI: Brain's level and why, the
findings, the line at risk, data labels and sources, and how the text was
generated. Pages are A4 images at 150 dpi, so the text is not selectable.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DPI = 150
PAGE = (1240, 1754)  # A4 at 150 dpi
MARGIN = 110
INK, MUTED, RULE, WARN = (20, 28, 36), (90, 102, 114), (200, 206, 212), (176, 92, 20)
# Regular and bold faces with the symbols the reports use (·, —, °, ≥, →); Pillow's own font is the last resort.
FONTS = {"regular": ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                     "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         "bold": ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf",
                  "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")}
STYLES = {"title": ("bold", 34, INK), "banner": ("bold", 22, WARN), "heading": ("bold", 24, INK),
          "body": ("regular", 21, INK), "small": ("regular", 18, MUTED), "fact": ("regular", 19, INK)}
DATA_BANNERS = {"SIMULATED": "SIMULATED DATA · fictional vessel and track · exercise use only",
                "EXERCISE": "EXERCISE DATA · fictional exercise vessel and track",
                "REAL": "REAL AIS · public data · self-reported, not verified"}


def _font(face: str, size: int):
    for name in FONTS[face]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def check_status(check: dict | None, text: str) -> list[str]:
    """What the last Check report said, and whether the text changed after it."""
    if not check:
        return ["Not checked: Check report was not run on this text."]
    if check.get("text_hash") != text_hash(text):
        return ["Not checked since the last edit: run Check report again before sending."]
    code, ai = check["result"]["code"], check["result"]["ai"]
    lines = ["Code check (exact, no AI): " + ("consistent with system data." if code["consistent"] else
                                           f"{len(code['findings'])} finding(s) open.")]
    if "unavailable" in ai:
        lines.append(f"AI check (meaning): not run ({ai['unavailable']}).")
    else:
        lines.append(f"AI check (meaning, {ai['meta']['model']}): " +
                     ("no problems found." if ai["consistent"] else f"{len(ai['findings'])} suggestion(s)."))
    for finding in code["findings"] + ai.get("findings", []):
        quote = f" “{finding['quote']}”" if finding["quote"] else ""
        lines.append(f"- {finding['layer'].upper()} {finding['kind']}{quote}: {finding['problem']}")
    return lines


def blocks(pack: dict, text: str, category: str, *, check: dict | None = None, generation: dict | None = None,
           created_utc: str | None = None) -> list[tuple[str, str]]:
    """The report as (style, text) blocks, in order. The appendix comes from the pack alone."""
    vessel = pack["vessel"]
    created = created_utc or datetime.now(timezone.utc).isoformat(timespec="seconds")
    found = [("title", "Analyst report — draft for review"),
             ("banner", DATA_BANNERS.get(pack["data_tag"], f"{pack['data_tag']} DATA")),
             ("body", f"Vessel: {vessel['name']} · {vessel['id']} · {vessel['label']}"),
             ("body", f"Category: {category}")]
    incident = [fact["text"] for fact in pack["facts"] if fact["topic"] == "incident"]
    if incident:
        found.append(("body", incident[0]))
    found += [("small", f"Prepared {created} · evidence: {pack['summary']}"),
              ("small", "Human review required. No operational action has been triggered."),
              ("heading", "Report"), *[("body", line) for line in (text or "").strip().splitlines()],
              ("heading", "Check status"), *[("body", line) for line in check_status(check, text)]]
    found.append(("heading", "Appendix A · Brain level and why (built by code, not AI)"))
    level = pack["level"]
    if level:
        found.append(("body", f"Brain level {level['name']}, score {level['score']}. The level is a rule outcome "
                              "for human review, not a probability of hostile intent; this report does not change it."))
    else:
        found.append(("body", "No Brain assessment: this vessel is not scored by the incident detector."))
    for topic in ("level", "factor", "rule", "finding", "small_vessel", "line", "line_other", "incident",
                  "responders", "recommendation", "no_action", "data_issue"):
        for fact in pack["facts"]:
            if fact["topic"] == topic:
                found.append(("fact", f"{fact['id']} [{fact['label']}] {fact['text']}"))
    found.append(("heading", "Appendix B · Identity, position, data labels and sources"))
    for fact in pack["facts"]:
        if fact["topic"] in ("identity", "source", "position", "motion", "destination", "raised", "summary",
                             "data_label", "ais_limit", "no_brain"):
            found.append(("fact", f"{fact['id']} [{fact['label']}] {fact['text']}"))
    found.append(("heading", "Appendix C · How the text was produced"))
    generation = generation or {}
    method = {"ai": "AI-assisted draft, validated by code against the evidence",
              "template": "Template draft written by code from the evidence (no AI)"}.get(
        generation.get("method"), "Written by the analyst (no draft tool used)")
    found.append(("body", f"Method: {method}."))
    if generation.get("method"):
        details = [f"generated {generation['generated_utc']}"]
        if generation.get("model"):
            details.insert(0, f"model {generation['model']}")
        if generation.get("cost_usd") is not None:
            details.append("from cache, no cost" if generation.get("cached") else
                           f"reported cost ${generation['cost_usd']:.4f}")
        if generation.get("fallback"):
            details.append(f"AI not used: {generation['fallback']}")
        line = "; ".join(details)
        found.append(("body", line[0].upper() + line[1:] + "."))
        found.append(("body", f"Evidence IDs used by the draft: {', '.join(generation.get('evidence') or [])}."))
    found.append(("small", "The analyst is responsible for the report text and reviews it before sending. "
                           "Evidence IDs refer to Appendices A and B."))
    return found


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip() if current else word
        if draw.textlength(candidate, font=font) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    return lines + [current] if current or not lines else lines


def render(found: list[tuple[str, str]], footer: str) -> list[Image.Image]:
    """A4 pages at 150 dpi with a footer and page numbers."""
    fonts = {style: _font(face, size) for style, (face, size, _colour) in STYLES.items()}
    pages, width, bottom = [], PAGE[0] - 2 * MARGIN, PAGE[1] - MARGIN - 40

    def new_page():
        page = Image.new("RGB", PAGE, "white")
        pages.append(page)
        return page, ImageDraw.Draw(page), MARGIN

    page, draw, y = new_page()
    for style, text in found:
        font, colour = fonts[style], STYLES[style][2]
        size = STYLES[style][1]
        gap_before = {"heading": 26, "title": 0, "banner": 6}.get(style, 4)
        lines = _wrap(draw, text, font, width) if text else [""]
        if style == "heading" and y + gap_before + 3 * size > bottom:
            page, draw, y = new_page()
        y += gap_before
        for line in lines:
            if y + size * 1.4 > bottom:
                page, draw, y = new_page()
            draw.text((MARGIN, y), line, font=font, fill=colour)
            y += round(size * 1.4)
        if style == "heading":
            draw.line((MARGIN, y + 2, PAGE[0] - MARGIN, y + 2), fill=RULE, width=2)
            y += 10
    small = fonts["small"]
    for number, page in enumerate(pages, 1):
        ImageDraw.Draw(page).text((MARGIN, PAGE[1] - MARGIN), f"{footer} · page {number} of {len(pages)}",
                                  font=small, fill=MUTED)
    return pages


def save_pdf(path, pack: dict, text: str, category: str, *, check: dict | None = None,
             generation: dict | None = None, created_utc: str | None = None) -> Path:
    path = Path(path)
    found = blocks(pack, text, category, check=check, generation=generation, created_utc=created_utc)
    footer = f"Argus Mara · analyst report · {pack['vessel']['name']} · {pack['data_tag']} · draft for review"
    pages = render(found, footer)
    pages[0].save(path, "PDF", resolution=DPI, save_all=True, append_images=pages[1:],
                  title=f"Analyst report — {pack['vessel']['name']} ({pack['data_tag']})", author="Argus Mara",
                  subject="Analyst report, draft for review")
    return path
