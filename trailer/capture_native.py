"""Capture actual native screens using existing local evidence, with background analysis off.

No synthetic leads, new analyses, reports or decisions are created. User preferences,
AIS caches and the signed decision log are not overwritten.
"""
import os
import sys
import time
import json
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
temporary=Path(tempfile.mkdtemp(prefix='argus-trailer-'))
os.environ['ARGUS_AIS_AUTOCONNECT']='0'
os.environ['ARGUS_SATELLITE_AUTOSTART']='0'
os.environ['ARGUS_SUPABASE_READ']='0'
os.environ['ARGUS_REAL_ALERTS']='0'
os.environ['ARGUS_UI_PREFERENCES']=str(temporary/'preferences.json')
os.environ['ARGUS_DECISION_LOG']=str(temporary/'decisions.jsonl')

import customtkinter as ctk
from PIL import ImageGrab
import desktop_pro
import run_gui

OUTPUT=ROOT/'trailer/public/native'
OUTPUT.mkdir(parents=True,exist_ok=True)
ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')
desktop_pro.apply_palette()
root=ctk.CTk()
app=run_gui.ArgusApp(root,*run_gui.load_demo())
app.ais_tracker.cache_path=None
root.geometry('1500x790+0+0')
root.attributes('-topmost',True)
root.lift()

def pump(seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        root.update()
        time.sleep(.02)

def shot(name):
    root.update()
    x,y=root.winfo_rootx(),root.winfo_rooty()
    ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height())).save(OUTPUT/f'{name}.png')
    print('Captured',name,flush=True)

try:
    app.hide_exercise()
    app.alert_board.show_demo_alerts.set(False)
    app.alert_board.toggle_demo_alerts()
    pump(10)
    app.fit_ireland()
    pump(3)
    shot('overview')
    app.open_window('ais')
    pump(2)
    shot('ais')
    app.open_window('ports')
    pump(1)
    shot('ports')
    app.open_window('cables')
    pump(1)
    shot('cables')
    app.open_window('satellite')
    pump(3)
    shot('coast-watch')
    reviews=[]
    for path in (ROOT/'data/satellite/reviews').glob('*.json'):
        try:
            value=json.loads(path.read_text(encoding='utf-8'))
            if value.get('scene',{}).get('sensor')=='Sentinel-2' and value.get('contacts'):
                reviews.append(value)
        except (OSError,ValueError):
            pass
    if reviews:
        review=max(reviews,key=lambda v:sum(c.get('confidence')=='medium' and (c.get('localization') or {}).get('status')=='anchored' for c in v.get('contacts',[])))
        identifier=review['scene']['id']
        app.satellite.open_review(identifier)
        pump(6)
        shot('satellite-review')
        contacts=app.satellite.current.get('contacts',[]) if app.satellite.current else []
        if contacts:
            point=next((c for c in contacts if str(c.get('id','')).startswith('AI') and (c.get('localization') or {}).get('status')=='anchored'),contacts[0])
            app.satellite.show_contact(point)
            pump(2)
            shot('contact-comparison')
    app.satellite.open_fleet()
    pump(3)
    shot('fleet-history')
    app.hide_console_panel()
    ships=list(app.ais_tracker.state.vessels.values())
    ship=next((v for v in ships if v.get('name') and v.get('lat') and v.get('lon')),None)
    if ship:
        import desktop_reports
        window=desktop_reports.open_report(app,desktop_reports.live_snapshot(ship))
        pump(2)
        shot('analyst-report')
    manifest={'captured_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
              'dataset_mode':'Real local cached observations; no live refresh or new AI analysis during capture',
              'ais_vessels_in_cache':len(ships),'ais_positions_rendered':len(app.ais_tracker.positions()),'satellite_reviews_considered':len(reviews),
              'screens':sorted(p.name for p in OUTPUT.glob('*.png'))}
    (OUTPUT/'capture-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
finally:
    app.close()
