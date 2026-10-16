"""The professional console look: night palette, square controls, marking banners and a DTG clock.

`python run_gui.py` opens this look; `python run_gui.py --old` (the *-OLD-* launchers) keeps the
original one. Only colours, chrome and the base map change; every tool and panel is shared.
"""
import sys

import customtkinter as ctk

import desktop_basemap

# After the IHO S-52 night tables and common C2 consoles: near-black surfaces, low-contrast
# lines, one cyan accent, amber kept for warnings.
PALETTE = {
    "BG": "#05090d",
    "CARD": "#0b1218",
    "INK": "#dbe5ea",
    "MUTED": "#8fa1ac",
    "LINE": "#1f2e38",
    "TEAL": "#46d1c4",
    "AMBER": "#e8b04a",
    "SEA": "#03080d",
    "PURPLE": "#d4b25e",
    "CONTROL": "#0f1920",
    "HOVER": "#182833",
}
# Green banner = unclassified (US CAPCO colour, as used by Astro UX). Everything shown is public data.
MARKING = "UNCLASSIFIED // EXERCISE // PUBLIC DATA ONLY"
MARKING_BG = "#007A33"


def apply_palette() -> None:
    """Switch both copies of run_gui (the script and the imported module) to the pro look."""
    import run_gui
    for module in {sys.modules.get("__main__"), run_gui}:
        if module is None or not hasattr(module, "UI_EDITION"):
            continue
        module.UI_EDITION = "pro"
        for name, value in PALETTE.items():
            setattr(module, name, value)
    for name in ("CTkButton", "CTkEntry", "CTkFrame", "CTkOptionMenu", "CTkComboBox"):
        if name in ctk.ThemeManager.theme:
            ctk.ThemeManager.theme[name]["corner_radius"] = 3
    # Check boxes and switches in the console accent instead of the default blue.
    accent, accent_hover = "#1f8f86", "#26a89d"
    for name in ("CTkCheckBox", "CTkSwitch", "CTkRadioButton"):
        theme = ctk.ThemeManager.theme.get(name)
        if theme is None:
            continue
        for key, value in (("fg_color", accent), ("hover_color", accent_hover), ("progress_color", accent),
                           ("border_color", PALETTE["LINE"])):
            if key in theme:
                theme[key] = [value, value]
        if "corner_radius" in theme and name == "CTkCheckBox":
            theme["corner_radius"] = 2


def _banner(root, before, side: str):
    banner = ctk.CTkLabel(root, text=MARKING, fg_color=MARKING_BG, text_color="#ffffff", height=20,
                          corner_radius=0, font=ctk.CTkFont(desktop_basemap.MONO, 11, "bold"))
    banner.pack(side=side, fill="x", before=before)
    return banner


def decorate(app) -> None:
    """Marking banners at the top and bottom of the window and a date-time group in the header."""
    shell = app.workspace.master
    app.marking_banners = (_banner(app.root, shell, "top"), _banner(app.root, shell, "bottom"))
    utc = app.utc_header.master
    caption = next((child for child in utc.winfo_children() if child is not app.utc_header), None)

    def tick():
        if caption is not None and caption.winfo_exists():
            caption.configure(text=f"DTG {desktop_basemap.dtg()}")
            app.root.after(5000, tick)

    tick()
