"""Connect Global Fishing Watch radar detections without putting the token in Git.

Register for a free, non-commercial API token at
https://globalfishingwatch.org/our-apis/tokens and paste it when asked. It is hidden
while typing, checked with one small radar report, and saved in this computer's
credential store (service ArgusMara.GFW). GFW_API_TOKEN in the environment
overrides it. Never put the token in chat, Git or command arguments: GFW's terms
say it is personal and must not be shared or published.
"""
import argparse
from getpass import getpass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus import gfw_sar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-check', action='store_true', help='save without the test report request')
    args = parser.parse_args()
    token = getpass('Global Fishing Watch API token (hidden): ').strip()
    if not gfw_sar.valid_token(token):
        parser.exit(1, 'That does not look like a Global Fishing Watch API token; nothing changed.\n')
    if not args.no_check:
        try:
            check = gfw_sar.check_token(token)
        except ValueError as error:
            parser.exit(1, str(error) + '\nNothing changed.\n')
        print('Global Fishing Watch answered:', json.dumps(check))
    try:
        gfw_sar.save_token(token)
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
    print('Saved in this computer’s credential store (%s).' % gfw_sar.SERVICE)
    print('Fetch radar contacts: python -m argus.gfw_sar fetch --days 14')
    print('Or open Satellite analysis → Coast Watch → Fetch radar. Show "%s" with the data.' % gfw_sar.ATTRIBUTION)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
