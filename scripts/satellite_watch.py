"""One-step Satellite Watch setup: keys, team database, AI budget and fresh images.

The SATELLITE-WATCH launchers run this before opening the app with
`run_gui.py --coast-watch`. A missing key is typed hidden, checked with a free
call and saved only in this computer's credential store; keys are never printed.
`--check` prints the same readiness without asking anything: exit 0 means ready
(image readers, TensorX and the team database), 3 means something is missing.
"""
import argparse
from datetime import datetime, timedelta, timezone
from getpass import getpass
from importlib.util import find_spec
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus import satellite, satellite_ai, supabase_ais
from argus.satellite import atomic_json
from argus.satellite_scan import FRESH_DEFAULT_H, grid, max_image_age
from argus.space import timestamp

NOT_READY = 3
REPEAT = timedelta(days=10)  # Sentinel-2 repeats its ground track every 10 days.


def readers_installed():
    return all(find_spec(name) is not None for name in ('numpy', 'rasterio'))


def tensorx_connected():
    try:
        return bool(satellite_ai.get_key())
    except ValueError:
        return False


def connect_tensorx(root, ask=getpass, choose=satellite_ai.choose_model, save=satellite_ai.save_key, attempts=3):
    """Ask for the key hidden, verify it with free model discovery, then save it."""
    for _ in range(attempts):
        key = ask('TensorX API key (hidden, Enter to skip): ').strip()
        if not key:
            return None
        try:
            model = choose(key)
            save(key)
        except ValueError as error:
            print('  Not saved:', error)
            continue
        atomic_json(Path(root)/'ai/model.json', model)
        return model
    return None


def connect_database(root, ask=getpass, rpc=supabase_ais.http_rpc, save=supabase_ais.save_key,
                     link=supabase_ais.link, attempts=3):
    """Ask for the team database secret key hidden, check it with one free status call, then link."""
    for _ in range(attempts):
        key = ask('Team database secret key, sb_secret_... (hidden, Enter to skip): ').strip()
        if not key:
            return None
        if not supabase_ais.valid_key(key):
            print('  Not saved: that is not a Supabase secret key (sb_secret_...)')
            continue
        try:
            state = rpc(supabase_ais.base_url()+'/rest/v1/rpc/argus_ais_status', {}, key)
            save(key)
            link(root)
        except (ValueError, OSError) as error:
            print('  Not saved:', error)
            continue
        return state
    return None


def budget(root):
    """The pilot ledger, and roughly how many more image checks fit under the ceiling.

    Each call needs one full reservation of headroom when it starts and then
    settles at its real cost, so after the first calls the estimate uses their
    measured average cost; before that it assumes the worst-case reservation.
    """
    root = Path(root)
    ledger = satellite_ai.read_ledger(root/'ai')
    left = max(0., satellite_ai.PILOT_USD-ledger['reserved_usd'])
    model_path = root/'ai/model.json'
    reserve = json.loads(model_path.read_text(encoding='utf-8')).get('reservation_usd') if model_path.exists() else None
    reserve = reserve if isinstance(reserve, (int, float)) and reserve > 0 else None
    measured = ledger['reported_usd']/ledger['calls'] if ledger['calls'] and ledger['reported_usd'] > 0 else None
    if reserve and measured:
        calls, basis = math.floor(max(0., left-reserve)/measured+1e-9), 'measured'
    elif reserve:
        calls, basis = math.floor(left/reserve+1e-9), 'worst case'
    else:
        calls, basis = None, None
    return {'reserved_usd': ledger['reserved_usd'], 'left_usd': left, 'calls_left': calls, 'basis': basis,
            'per_check_usd': measured if basis == 'measured' else reserve, 'halted': bool(ledger.get('halted'))}


def coastal_region():
    boxes = [tile['bbox'] for tile in grid()['tiles']]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def passes(rows, gap_s=1800):
    """Group catalogue granules into satellite passes, newest first."""
    groups = []
    for row in sorted(rows, key=lambda r: r['acquired_utc']):
        moment = timestamp(row['acquired_utc'])
        if groups and moment-groups[-1]['last'] <= gap_s:
            groups[-1]['rows'].append(row)
            groups[-1]['last'] = moment
        else:
            groups.append({'rows': [row], 'last': moment})
    result = []
    for group in reversed(groups):
        rows = group['rows']
        clouds = sorted(r['cloud_percent'] for r in rows if isinstance(r.get('cloud_percent'), (int, float)))
        first, last = timestamp(rows[0]['acquired_utc']), timestamp(rows[-1]['acquired_utc'])
        result.append({'first_utc': rows[0]['acquired_utc'], 'last_utc': rows[-1]['acquired_utc'],
                       'middle_utc': iso(datetime.fromtimestamp((first+last)/2, timezone.utc)),
                       'granules': len(rows), 'median_cloud': clouds[len(clouds)//2] if clouds else None})
    return result


def expected_passes(now, hours, seen, search=satellite.search):
    """Passes of the same window 10 days ago, shifted forward, that the catalogue does not list yet."""
    start = now-timedelta(hours=12)
    earlier = passes(search('Sentinel-2', coastal_region(), iso(start-REPEAT), iso(now+timedelta(hours=hours)-REPEAT),
                            all_pages=True))
    result = []
    for row in earlier:
        first = datetime.fromtimestamp(timestamp(row['first_utc']), timezone.utc)+REPEAT
        if first < start or any(abs(timestamp(p['first_utc'])-first.timestamp()) < 3600 for p in seen):
            continue
        result.append({**row, 'first_utc': iso(first),
                       'last_utc': iso(datetime.fromtimestamp(timestamp(row['last_utc']), timezone.utc)+REPEAT),
                       'taken': first < now})
    return result


def ships_at(moment, region, rows_for=supabase_ais.ais_rows):
    """Distinct ships the team database holds within 10 minutes of a moment."""
    packet = rows_for(moment, region)
    rows = packet.get('rows') if isinstance(packet, dict) else None
    if not isinstance(rows, list):
        raise ValueError('Unexpected database answer')
    return len({row.get('mmsi') for row in rows if isinstance(row, dict) and row.get('msg_type') == 'PositionReport'})


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def when(value):
    return datetime.fromtimestamp(timestamp(value), timezone.utc).strftime('%d %b %H:%M')


def span(row):
    first, last = when(row['first_utc']), when(row['last_utc'])
    return f'{first} UTC' if first == last else f'{first}–{last[-5:]} UTC'


def show_database(now):
    """Print the feed state; the answer (or None) also gives the usual number of ships."""
    try:
        state = supabase_ais.status()
    except ValueError as error:
        print('  Team database   linked, but not answering:', error)
        return None
    newest = state.get('newest_utc')
    age = f'newest AIS {max(0, round((now.timestamp()-timestamp(newest))/60))} min ago' if newest else 'no AIS yet'
    print(f"  Team database   linked · {age} · {state.get('vessels_last_hour', 0)} ships in the last hour")
    return state


def ais_note(ships, usual):
    if not ships:
        return ' · no AIS in the database at that time'
    thin = f' (thin: usually about {usual})' if isinstance(usual, int) and ships < usual/4 else ''
    return f' · {ships} ships in the database at that time{thin}'


def show_images(now, hours, database):
    region = coastal_region()
    try:
        recent = passes(satellite.search('Sentinel-2', region, iso(now-timedelta(hours=hours)), iso(now), all_pages=True))
        expected = expected_passes(now, hours, recent)
    except ValueError as error:
        print('  Images          catalogue unavailable:', error)
        return
    print(f'  Images          Coast Watch reviews Sentinel-2 images taken in the last {hours:g} h')
    for row in recent:
        cloud = '' if row['median_cloud'] is None else f" · cloud about {row['median_cloud']:.0f} %"
        line = f"    {span(row)} · {row['granules']} granules{cloud}"
        if database is not None:
            try:
                line += ais_note(ships_at(row['middle_utc'], region), database.get('vessels_last_hour'))
            except ValueError:
                line += ' · database AIS check failed'
        print(line)
    if not recent:
        print('    none in the catalogue yet')
    for row in reversed(expected):  # soonest first
        state = 'taken, waiting for the catalogue' if row['taken'] else 'expected'
        print(f'    {span(row)} · {state} (same orbit as 10 days earlier); it usually appears 4–9 h after it is taken')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(ROOT/'data/satellite'), help='satellite workspace')
    parser.add_argument('--check', action='store_true', help='print readiness without asking for keys')
    args = parser.parse_args(argv)
    try:
        fresh = max_image_age()
    except ValueError as error:
        parser.exit(1, f'{error}\n')
    hours = fresh.total_seconds()/3600 if fresh else FRESH_DEFAULT_H
    root = Path(args.root)
    now = datetime.now(timezone.utc)
    print('ARGUS MARA · Satellite Watch')

    readers = readers_installed()
    print('  Image readers  ', 'installed' if readers else 'missing: pip install -r requirements-satellite.txt')

    if not supabase_ais.linked(root) and not args.check:
        if supabase_ais.configured():
            supabase_ais.link(root)  # The key is already stored; only this workspace was unlinked.
            print('  Team database key found in this computer’s credential store; workspace linked.')
        else:
            print('The team database is not linked on this computer. Paste its secret key once.')
            connect_database(root)
    database = show_database(now) if supabase_ais.linked(root) else None
    if not supabase_ais.linked(root):
        print('  Team database   not linked · only AIS this computer records from now on can be compared')

    if not tensorx_connected() and not args.check:
        print('TensorX is not connected. Paste its API key once; it is checked for free before saving.')
        connect_tensorx(root)
    ai = tensorx_connected()
    print('  TensorX AI     ', 'connected' if ai else 'not connected · free "AIS at image time" still works')

    money = budget(root)
    calls = (f" · about {money['calls_left']:,} more image checks ({money['basis']}, ${money['per_check_usd']:.4f} each)"
             if money['calls_left'] is not None else '')
    halted = ' · HALTED, check the ledger' if money['halted'] else ''
    print(f"  AI budget       ${money['reserved_usd']:.2f} of ${satellite_ai.PILOT_USD:.0f} reserved{calls}{halted}")

    show_images(now, hours, database)
    ready = readers and ai and database is not None
    if args.check:
        return 0 if ready else NOT_READY
    if ready:
        print('Ready. The app opens with Coast Watch running. Keep it open; results appear in the'
              ' Coast Watch list and in Incidents → Satellite / AIS review.')
    else:
        print('The app opens on Satellite analysis without automatic AI review until the items above are fixed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
