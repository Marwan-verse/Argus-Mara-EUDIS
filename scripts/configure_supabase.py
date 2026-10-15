"""Link Coast Watch to the team Supabase database without putting the key in Git.

Paste the project's secret key (Supabase dashboard -> Project Settings -> API Keys
-> Secret keys, sb_secret_...) when asked. The key is hidden while typing, checked
with one free status call, saved in this computer's credential store, and the
default workspace data/satellite is linked. --host prints the two lines for the
ignored Docker host environment file instead of saving anything.
"""
import argparse
from getpass import getpass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus import supabase_ais


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(ROOT/'data/satellite'), help='satellite workspace to link')
    parser.add_argument('--host', action='store_true', help='print host environment lines instead of saving')
    args = parser.parse_args()
    key = getpass('Supabase secret key (hidden): ').strip()
    if not supabase_ais.valid_key(key):
        parser.exit(1, 'That is not a Supabase secret key (sb_secret_...) or service_role key; nothing changed.\n')
    try:
        state = supabase_ais.http_rpc(supabase_ais.base_url() + '/rest/v1/rpc/argus_ais_status', {}, key)
    except ValueError as error:
        parser.exit(1, str(error) + '\nNothing changed.\n')
    print('Database answered:', json.dumps({k: state.get(k) for k in ('positions', 'vessels_last_hour', 'last_ok_utc', 'database_mb')}))
    if args.host:
        print('Add these two lines to the ignored host file data/satellite-host/tensorx.env, then rebuild the host:')
        print('  ARGUS_SUPABASE_LINK=1')
        print('  ARGUS_SUPABASE_KEY=<the key you just pasted>')
        print('Never commit or share that file.')
        return 0
    try:
        supabase_ais.save_key(key)
        path = supabase_ais.link(args.root)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    print('Saved in this computer’s credential store and linked', path.parent)
    print('Coast Watch now reads AIS from the database and saves image contacts there.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
