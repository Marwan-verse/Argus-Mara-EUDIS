"""Map-first native console: compact header, icon rails and chart popovers."""
import tkinter as tk
import os
from tkinter import ttk
import customtkinter as ctk

RAIL_WIDTH = 54


def build(app):
    import run_gui as ui
    from desktop_tools import ConsoleTools
    app.tools = ConsoleTools(app)
    app.toolbar_buttons = {}
    app.console_layout = True
    app.exercise_visible = tk.BooleanVar(app.root, value=False)
    app.panel_visible = False
    app.root.configure(fg_color=ui.BG)
    shell = ctk.CTkFrame(app.root, fg_color=ui.BG, corner_radius=0)
    shell.pack(fill="both", expand=True)

    header = ctk.CTkFrame(shell, height=64, fg_color=ui.BG, corner_radius=0)
    header.pack(fill="x")
    header.pack_propagate(False)
    brand = ctk.CTkFrame(header, fg_color="transparent")
    brand.pack(side="left", padx=20, pady=6)
    ctk.CTkLabel(brand, text="ARGUS MARA", image=app.tools.icons.get('brand', ui.PURPLE, 24),
                 compound='left', padx=8, text_color=ui.INK,
                 font=ctk.CTkFont("Segoe UI", 20, "bold")).pack(anchor="w")
    ctk.CTkLabel(brand, text="Maritime intelligence / Irish coast", text_color=ui.MUTED,
                 font=ctk.CTkFont("Segoe UI", 11)).pack(anchor="w", padx=8)
    search = ctk.CTkButton(header, text='Search  Ctrl+K', image=app.tools.icons.get('search'),
        command=app.tools.open_search, fg_color=ui.CONTROL, hover_color=ui.HOVER,
        text_color=ui.INK, width=142, height=34, corner_radius=8, font=ctk.CTkFont('Segoe UI', 12))
    search.pack(side='right', padx=(12, 18))
    ctk.CTkButton(header, text='SOC session', command=lambda: app.soc.open(),
                 width=110, height=34).pack(side='right', padx=6)
    mode = 'Offline demo' if app.soc_client is None else f"SOC · {app.soc_client.user['username']}"
    app.soc_mode_label = ctk.CTkLabel(header, text=mode, text_color=ui.MUTED)
    app.soc_mode_label.pack(side='right', padx=6)
    app.tools.style_button(search, 'Search ships, ports, views or coordinates · Ctrl+K')
    utc = ctk.CTkFrame(header, fg_color='transparent')
    utc.pack(side='right', padx=14)
    ctk.CTkLabel(utc, text='UTC', text_color=ui.MUTED, font=ctk.CTkFont('Segoe UI', 11)).pack(anchor='w')
    app.utc_header = ctk.CTkLabel(utc, text='--:--:--Z', text_color=ui.INK, font=ctk.CTkFont('Consolas', 13))
    app.utc_header.pack(anchor='w')
    counts = ctk.CTkFrame(header, fg_color='transparent')
    counts.pack(side='right', padx=14)
    ctk.CTkLabel(counts, text='Ships / fresh fixes', text_color=ui.MUTED, font=ctk.CTkFont('Segoe UI', 11)).pack(anchor='w')
    app.feed_counts_label = ctk.CTkLabel(counts, text='0 / 0', text_color=ui.INK, font=ctk.CTkFont('Consolas', 13))
    app.feed_counts_label.pack(anchor='w')
    app.feed_header = ctk.CTkLabel(header, text='Connecting', text_color=ui.MUTED,
        fg_color=ui.CONTROL, corner_radius=8, width=105, height=30, font=ctk.CTkFont('Segoe UI', 12))
    app.feed_header.pack(side='right', padx=12)
    ctk.CTkFrame(shell, height=1, fg_color=ui.LINE).pack(fill="x")

    app.workspace = ttk.Panedwindow(shell, orient="vertical")
    app.workspace.pack(fill="both", expand=True)
    app.main_split = ttk.Panedwindow(app.workspace, orient="horizontal")
    app.workspace.add(app.main_split, weight=5)
    # Columns: icon rail, docked alert board, then the map and its overlays.
    chart = ctk.CTkFrame(app.main_split, fg_color=ui.BG, corner_radius=0)
    app.chart_frame = chart
    app.main_split.add(chart, weight=1)
    app.alerts_panel = tk.Frame(chart, bg=ui.CARD, highlightthickness=0)
    map_host = tk.Frame(chart, bg=ui.SEA, highlightthickness=0)
    app.chart_host = map_host
    app.map = tk.Canvas(map_host, bg=ui.SEA, highlightthickness=0)
    app.map.pack(fill="both", expand=True)
    app.map.bind("<Configure>", app._map_resized)
    app.map.bind("<ButtonPress-1>", app._pan_start)
    app.map.bind("<B1-Motion>", app._pan_move)
    app.map.bind("<ButtonRelease-1>", app._pan_end)
    app._last_scroll_zoom = (0.0, 0)
    app.map.bind("<MouseWheel>", app._mouse_wheel)
    app.map.bind("<Button-4>", lambda e: app._mouse_wheel(e, 1))
    app.map.bind("<Button-5>", lambda e: app._mouse_wheel(e, -1))
    try:
        app.map.bind("<TouchpadScroll>", app._touchpad_scroll)
    except tk.TclError:
        pass
    app.map.bind("<Motion>", app._map_motion)
    # Trackpads: two-finger scrolling of lists on Tk 9, and pinch to zoom the map on macOS.
    from desktop_gestures import PinchZoom, install_touchpad_scroll
    install_touchpad_scroll(app.root)
    app.pinch = PinchZoom(app)

    def button(parent, icon, action, title=None):
        control = ctk.CTkButton(parent, text='', image=app.tools.icons.get(icon), command=action, width=38, height=36,
            corner_radius=6, fg_color="transparent", hover_color=ui.CONTROL,
            text_color=ui.MUTED)
        control.pack(padx=4, pady=3)
        app.tools.style_button(control, title)
        app.toolbar_buttons[icon] = control
        return control

    left = ctk.CTkFrame(chart, fg_color=ui.BG, corner_radius=0, width=RAIL_WIDTH)
    left.place(x=0, y=0, relheight=1)
    left.pack_propagate(False)
    for icon, title, action in (
        ("alerts", "Show / hide alerts", app.tools.toggle_alerts),
        ("ship", "Maritime / AIS ships", lambda: app.open_window("ais")),
        ("views", "Saved map views", lambda: app.open_window('views')),
        ("cables", "Historical cable routes", lambda: app.open_window("cables")),
        ("ports", "Port directory", lambda: app.open_window("ports")),
        ("radar", "Satellite analysis / historical AIS", lambda: app.open_window("satellite")),
        ("weather", "Weather", lambda: app.open_window("weather")),
        ("layers", "Display layers", lambda: app.open_window("layers")),
    ):
        button(left, icon, action, title)
    ctk.CTkFrame(left, width=30, height=1, fg_color=ui.LINE).pack(fill="x", padx=10, pady=8)
    button(left, "replay", app.show_exercise, "Fictional exercise replay")
    button(left, "evidence", app.review_evidence, "Exercise evidence review")

    def layout_columns():
        """Place the docked alerts beside the rail and give the map the remaining width."""
        scaling = ctk.ScalingTracker.get_widget_scaling(chart)
        rail = round(RAIL_WIDTH * scaling)
        width = round(app.tools.alert_width * scaling) if app.tools.alerts_visible else 0
        if getattr(app, '_column_layout', None) == (rail, width):
            return
        app._column_layout = (rail, width)
        if width:
            app.alerts_panel.place(x=rail, y=0, width=width, relheight=1)
        else:
            app.alerts_panel.place_forget()
        map_host.place(x=rail + width, y=0, relwidth=1, width=-(rail + width), relheight=1)
        if hasattr(app, 'alert_board') and width:
            app.alert_board.set_width(width)

    app.layout_columns = layout_columns
    app.alert_cards = []
    from desktop_alerts import AlertBoard
    AlertBoard(app, app.alerts_panel)
    layout_columns()

    right = ctk.CTkFrame(map_host, fg_color=ui.BG, corner_radius=18)
    right.place(relx=1, x=-12, y=80, anchor="ne")
    for icon, title, action in (
        ("search", "Global search / Ctrl+K", app.tools.open_search),
        ("radar", "Satellite analysis", lambda: app.open_window("satellite")),
        ("alerts", "Show / hide alerts", app.tools.toggle_alerts),
        ("pen", "Add map note", lambda: app._set_map_tool("pin")),
        ("measure", "Measure distance", lambda: app._set_map_tool("measure")),
        ("ping", "Ping map · click a point · Escape to clear", lambda: app._set_map_tool("ping")),
        ("layers", "Map layers", lambda: app.open_window("layers")),
    ):
        button(right, icon, action, title)
    app.map.bind('<Escape>', app._clear_map_ping, add='+')

    app.floating_panel = ctk.CTkFrame(map_host, fg_color=ui.CARD, corner_radius=8,
                                      border_width=1, border_color=ui.LINE)
    # The map layout supplies its dimensions. A scrollable tab's small requested
    # height must not shrink the whole dock and hide most satellite controls.
    app.floating_panel.pack_propagate(False)
    panel_head = ctk.CTkFrame(app.floating_panel, fg_color="transparent")
    panel_head.pack(fill="x", padx=12, pady=(8, 2))
    app.panel_caption = ctk.CTkLabel(panel_head, text="Maritime", text_color=ui.INK,
                                    font=ctk.CTkFont("Segoe UI", 16, "bold"))
    app.panel_caption.pack(side="left")
    app.windows_plus = ctk.CTkButton(panel_head, text='', image=app.tools.icons.get('plus'), width=30, height=30,
        fg_color="transparent", text_color=ui.MUTED, command=app.open_windows_menu)
    app.windows_plus.pack(side="right", padx=4)
    app.tools.style_button(app.windows_plus, 'Add a panel')
    close = ctk.CTkButton(panel_head, text='', image=app.tools.icons.get('close'), width=30, height=30,
                         fg_color='transparent', hover_color=ui.HOVER, command=app.hide_console_panel)
    close.pack(side='right')
    app.tools.style_button(close, 'Hide this panel')
    app.close_panel_button = ctk.CTkButton(panel_head, text="Close tab", width=65, height=25,
        fg_color="transparent", text_color=ui.MUTED, command=app.close_current_panel)
    app.close_panel_button.pack(side="right")
    app.tools.style_button(app.close_panel_button, 'Close the selected tab')
    app.tools.make_movable((panel_head, app.panel_caption))
    app.right_notebook = ttk.Notebook(app.floating_panel, style="Dock.TNotebook")
    app.right_notebook.pack(fill="both", expand=True, padx=8, pady=(2, 8))
    app._bind_dock(app.right_notebook)
    overview = ttk.Frame(app.right_notebook)
    app.right_notebook.add(overview, text="Exercise")
    content = ctk.CTkScrollableFrame(overview, fg_color=ui.CARD, corner_radius=0)
    content.pack(fill="both", expand=True)
    ctk.CTkLabel(content, text="Fictional exercise", text_color=ui.MUTED,
                 font=ctk.CTkFont("Segoe UI", 12, "bold")).pack(anchor="w")
    ctk.CTkLabel(content, text=app.vessel["name"], text_color=ui.INK,
                 font=ctk.CTkFont("Segoe UI", 19, "bold")).pack(anchor="w", pady=(8, 4))

    def label(color=ui.INK, size=13):
        widget = ctk.CTkLabel(content, text="", text_color=color, justify="left", wraplength=330,
                              font=ctk.CTkFont("Segoe UI", size))
        widget.pack(anchor="w", pady=5)
        return widget

    app.state_label = label(ui.AMBER)
    ctk.CTkLabel(content, text="Expected time to cable", text_color=ui.MUTED,
                 font=ctk.CTkFont("Segoe UI", 12)).pack(anchor="w", pady=(10, 0))
    app.countdown_label = label(ui.PURPLE, 32)
    app.countdown_label.configure(font=ctk.CTkFont('Consolas', 32, 'bold'), text_color=ui.AMBER)
    app.earliest_label = label()
    app.distance_label = label(ui.MUTED)
    app.reasons_label = label()
    app.options_label = label()
    app.approve_button = ctk.CTkButton(content, text="Review response", command=app.review_response,
        fg_color=ui.PURPLE, text_color=ui.BG, hover_color='#af9450', corner_radius=8)
    app.approve_button.pack(fill="x", pady=8)
    app.approval_label = label(ui.MUTED)
    ctk.CTkLabel(content, text="No operational action is sent.", text_color=ui.MUTED).pack(anchor="w")
    # The replay renderer retains its existing fields; these values live in the
    # exercise panel rather than occupying four permanent dashboard cards.
    app.summary_state_label = ctk.CTkLabel(content, text="")
    app.summary_countdown_label = ctk.CTkLabel(content, text="")
    app.summary_distance_label = ctk.CTkLabel(content, text="")
    app.summary_beat_label = ctk.CTkLabel(content, text="")
    app.time_label = label(ui.MUTED)
    app.time_label.configure(font=ctk.CTkFont('Consolas', 11))

    app.bottom_dock = ctk.CTkFrame(app.workspace, fg_color=ui.CARD, corner_radius=0)
    bottom_header = ctk.CTkFrame(app.bottom_dock, fg_color="transparent")
    bottom_header.pack(fill="x", padx=12)
    ctk.CTkButton(bottom_header, text="Move tabs right / close pane", command=app.move_bottom_tabs_right,
        fg_color=ui.CONTROL, text_color=ui.INK, height=26).pack(side="right", pady=4)
    app.bottom_notebook = ttk.Notebook(app.bottom_dock, style="Dock.TNotebook")
    app.bottom_notebook.pack(fill="both", expand=True, padx=8, pady=8)
    app._bind_dock(app.bottom_notebook)

    navigation = ctk.CTkFrame(map_host, fg_color=ui.BG, corner_radius=8)
    navigation.place(relx=1, rely=1, x=-14, y=-54, anchor="se")
    button(navigation, "plus", lambda: app._zoom_by(1), "Zoom in")
    button(navigation, "minus", lambda: app._zoom_by(-1), "Zoom out")
    button(navigation, "home", app.fit_ireland, "Fit Irish coastline")

    modes = ctk.CTkFrame(map_host, fg_color=ui.BG, corner_radius=8, border_width=1, border_color=ui.LINE)
    modes.place(x=16, rely=1, y=-54, anchor="sw")
    app.modes_bar = modes
    pro = ui.UI_EDITION == "pro"
    chart_mode = ui.desktop_basemap.TACTICAL_MAP if pro else "Offline coastline"
    imagery_mode = ui.desktop_basemap.HD_IMAGERY if pro else ui.ONLINE_MAP
    for icon, text, action in (("layers", 'Chart' if pro else 'Map', lambda: app._change_map_mode(chart_mode)),
                              ("satellite", 'Satellite', lambda: app._change_map_mode(imagery_mode)),
                              ("ship", 'AIS', lambda: app.open_window("ais")),
                              ("replay", 'Exercise', app.show_exercise)):
        mode = ctk.CTkButton(modes, text=text, image=app.tools.icons.get(icon, ui.PURPLE),
            command=action, fg_color='transparent', hover_color=ui.HOVER, text_color=ui.INK,
            width=85, height=34, corner_radius=8, font=ctk.CTkFont('Segoe UI', 12))
        mode.pack(side='left', padx=3, pady=4)
        app.tools.style_button(mode, text + ' view')
    # Existing layer controls can still set this selector and weather indicator.
    app.map_selector = ctk.CTkOptionMenu(map_host, variable=app.map_mode,
        values=["Offline coastline", ui.ONLINE_MAP, *ui.desktop_basemap.SOURCES], command=app._change_map_mode)
    app.weather_label = ctk.CTkLabel(map_host, text="", text_color=ui.MUTED)

    app.replay_controls = ctk.CTkFrame(map_host, fg_color=ui.CARD, corner_radius=8,
                                       border_width=1, border_color=ui.LINE)
    row = ctk.CTkFrame(app.replay_controls, fg_color="transparent")
    row.pack(fill="x", padx=10, pady=6)
    app.play_button = ctk.CTkButton(row, text="Play", command=app.toggle_play, width=65,
                                   fg_color=ui.PURPLE, text_color=ui.BG, hover_color='#af9450', height=30)
    app.play_button.pack(side="left")
    app.tools.style_button(app.play_button, 'Play or pause the fictional exercise')
    for text, action in (("Restart", lambda: app.seek(0)), ("Alert", lambda: app.seek(app.alert['t'])),
                         ("Hide exercise", app.hide_exercise)):
        replay_action = ctk.CTkButton(row, text=text, command=action, width=90, height=30,
            fg_color=ui.CONTROL, hover_color=ui.HOVER, text_color=ui.INK, corner_radius=8)
        replay_action.pack(side="left", padx=4)
        app.tools.style_button(replay_action, text)
    app.speed_selector = ctk.CTkOptionMenu(row, values=["1×", "30×", "60×", "120×"], width=75, height=28,
        fg_color=ui.CONTROL, button_color=ui.CONTROL, button_hover_color=ui.HOVER,
        dropdown_fg_color=ui.CARD, dropdown_text_color=ui.INK, dropdown_hover_color=ui.HOVER,
        text_color=ui.INK, command=lambda v: app.rate.set(int(v[:-1])))
    app.speed_selector.set(f"{app.rate.get()}×")
    app.speed_selector.pack(side="left", padx=4)
    app.beat_label = ctk.CTkLabel(row, text="", text_color=ui.MUTED)
    app.beat_label.pack(side="left", padx=4)
    app.tools_plus = ctk.CTkButton(row, text='', image=app.tools.icons.get('plus'), command=app.open_tools_menu,
                                  width=30, height=30, fg_color=ui.CONTROL, hover_color=ui.HOVER)
    app.tools_plus.pack(side="right")
    app.tools.style_button(app.tools_plus, 'Replay panels and map tools')
    app.timeline = ctk.CTkSlider(app.replay_controls, from_=0, to=app.duration,
        command=app._scale_changed, progress_color=ui.PURPLE, button_color=ui.PURPLE)
    app.timeline.pack(fill="x", padx=12, pady=(0, 8))

    footer = ctk.CTkFrame(map_host, height=31, fg_color=ui.BG, corner_radius=0)
    footer.place(relx=0, rely=1, relwidth=1, anchor="sw")
    app.map_status_label = ctk.CTkLabel(footer, text="Irish coastline · drag to pan · wheel to zoom",
        text_color=ui.MUTED, font=ctk.CTkFont("Segoe UI", 11))
    app.map_status_label.pack(side="left", padx=16)
    app.map_attribution_label = ctk.CTkLabel(footer, text="Natural Earth / NGA / TeleGeography",
        text_color=ui.MUTED, font=ctk.CTkFont("Segoe UI", 10))
    app.map_attribution_label.pack(side="right", padx=12)
    app.root.bind("<F11>", app.toggle_fullscreen)
    def fit_ireland_when_ready(tries=0):
        # Fit Ireland only once the map has its real size; a slow start (many AIS ships) used to fit the world.
        if (app.map.winfo_width() < 300 or app.map.winfo_height() < 300) and tries < 50:
            app.root.after(100, fit_ireland_when_ready, tries + 1)
            return
        app.fit_ireland()

    app.root.after(250, fit_ireland_when_ready)
    if os.environ.get("ARGUS_AIS_AUTOCONNECT", "1") != "0":
        app.root.after(350, app.ais_tracker.connect)
    app.tools.setup()
