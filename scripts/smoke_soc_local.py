"""Verify the running local Docker demo using its private sample environment."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from argus.collab_client import SOCClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', type=Path, required=True)
    parser.add_argument('--url', default='https://localhost:8443')
    args = parser.parse_args()
    private = Path(__file__).resolve().parents[1] / 'data/soc-local/demo.env'
    values = dict(line.split('=', 1) for line in private.read_text().splitlines() if line and not line.startswith('#'))
    clients = [SOCClient(args.url, ca_file=args.ca) for _ in range(2)]
    try:
        a, b = clients
        a.login('Marwan', values['ARGUS_DEMO_MARWAN_PASSWORD'])
        b.login('Igor', values['ARGUS_DEMO_IGOR_PASSWORD'])
        assert 'evidence.share' in a.user['permissions'] and 'evidence.share' not in b.user['permissions']
        room = a.create()  # Team session: accounts need not share a group.
        b.join(room['code'])
        a.lock()
        b.poll()
        assert a.cipher.safety_codes[b.user['id']] == b.cipher.safety_codes[a.user['id']]
        # Programmatic comparison is valid only in this synthetic, locally
        # controlled smoke check. Real analysts compare through a trusted channel.
        a.confirm()
        b.confirm()
        a.poll()
        b.poll()
        a.send('chat', {'text': 'Local Docker SOC smoke test'})
        assert b.poll()[0]['payload']['text'] == 'Local Docker SOC smoke test'
        b.send('ping', {'lat': 53.35, 'lon': -6.25})
        assert a.poll()[0]['payload'] == {'lat': 53.35, 'lon': -6.25}
        print('PASS: HTTPS certificate, sample account roles, E2EE chat and map ping')
    finally:
        for client in clients:
            try:
                client.logout()
            except Exception:
                pass


if __name__ == '__main__':
    main()
