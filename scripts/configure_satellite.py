"""Connect TensorX without putting a key in command arguments or Git.

Default: OS credential store for the desktop. --host: ignored host environment file.
Only free model catalogue endpoints are queried; no completion is generated.
"""
import argparse
from getpass import getpass
import os
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus.satellite_ai import choose_model, save_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', action='store_true', help='create the ignored host environment file used by soc/compose.satellite.yml')
    args = parser.parse_args()
    target = ROOT/'data/satellite-host/tensorx.env'
    if args.host and target.exists():
        parser.exit(1, 'A host secret already exists. This command does not overwrite or rotate it.\n')
    key = getpass('TensorX API key (hidden): ').strip()
    if not key:
        parser.exit(1, 'No key entered; nothing changed.\n')
    if args.host and not re.fullmatch(r'[A-Za-z0-9_.-]{16,512}', key):
        parser.exit(1, 'For a key with special characters, configure TENSORX_API_KEY through your host secret manager instead.\n')
    try:
        model = choose_model(key)
        if args.host:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write('TENSORX_API_KEY='+key+'\n')
                stream.flush()
                os.fsync(stream.fileno())
            print('Saved ignored host environment file. Restrict this folder to the host operator; never share or commit it.')
        else:
            save_key(key)
            print('Saved in this computer’s credential store.')
    except (ValueError, OSError) as error:
        parser.exit(1, str(error)+'\n')
    print('Available pilot model:', model['id'])
    print('Manual requests only; automatic analysis remains off. No AI credits used for setup.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
