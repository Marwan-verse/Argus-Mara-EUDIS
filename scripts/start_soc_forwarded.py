"""Host the existing account relay behind a VS Code forwarded HTTPS port."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus.collab_client import SOCClient, ClientError, forwarded_origin, server_url
from argus.soc_launcher import StartupError, docker_path

DEFAULT_VOLUME = 'argus-soc-local_local_accounts'
ACCOUNT_CHECK = ('import sqlite3; '
                 'db=sqlite3.connect("file:/data/accounts.sqlite3?mode=ro", uri=True); '
                 'count=db.execute("SELECT count(*) FROM users WHERE disabled=0").fetchone()[0]; '
                 'db.close(); raise SystemExit(0 if count else 2)')


@contextmanager
def forwarding_listener(port):
    """Give VS Code a live port while copying its URL; never serve disk files."""
    class SetupPage(BaseHTTPRequestHandler):
        server_version = 'ArgusSOCSetup'
        sys_version = ''

        def do_GET(self):
            code = 200 if self.path == '/' else 404
            body = b'Argus SOC setup. Copy the forwarded HTTPS address and paste it into the hosting terminal.'
            self.send_response(code)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass
    try:
        listener = ThreadingHTTPServer(('127.0.0.1', port), SetupPage)
    except OSError:
        # Recognize our own running gateway; never ask users to forward an
        # unknown service that happens to occupy the proposed port.
        try:
            with urlopen(f'http://127.0.0.1:{port}/healthz', timeout=2) as response:
                health = json.loads(response.read(8192))
            if isinstance(health, dict) and health.get('service') == 'argus-soc' and health.get('ready') is True:
                yield None
                return
        except (OSError, ValueError):
            pass
        raise StartupError('The local port is unavailable or belongs to another service. '
                           'Use --port with an unused port, then forward that same port.') from None
    worker = threading.Thread(target=listener.serve_forever, name='soc-forward-setup', daemon=True)
    worker.start()
    try:
        yield listener
    finally:
        listener.shutdown()
        listener.server_close()
        worker.join(timeout=2)


def run(command, environment):
    try:
        return subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except (OSError, subprocess.TimeoutExpired):
        raise StartupError('Docker could not finish. Check Docker Desktop and retry.') from None


def start(url, port=8765, accounts_volume=DEFAULT_VOLUME, *, execute=run, docker=None, progress=print):
    url = server_url(url)
    if not forwarded_origin(url):
        raise ValueError('Use the HTTPS Forwarded Address ending in .devtunnels.ms or .app.github.dev from VS Code')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Use a local port between 1024 and 65535')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', accounts_volume):
        raise ValueError('Enter a Docker account-volume name')
    docker = docker or docker_path()
    environment = {**os.environ, 'SOC_FORWARDED_URL': url, 'SOC_FORWARD_PORT': str(port),
                   'SOC_ACCOUNTS_VOLUME': accounts_volume}
    if execute([docker, 'info', '--format', '{{.ServerVersion}}'], environment).returncode:
        raise StartupError('Start Docker Desktop/Engine, then retry. No accounts were changed.')
    if execute([docker, 'volume', 'inspect', accounts_volume], environment).returncode:
        raise StartupError('The existing account volume was not found. Start the local SOC setup once '
                           'to create your accounts, or pass --accounts-volume with their actual volume name.')
    # Never start another replica against a database owned by a different stack.
    owners = execute([docker, 'ps', '--filter', f'volume={accounts_volume}', '--format', '{{json .}}'], environment)
    if owners.returncode:
        raise StartupError('Cannot check the account volume owner. No containers were changed.')
    for line in owners.stdout.splitlines():
        try:
            labels = json.loads(line).get('Labels', '')
        except (ValueError, AttributeError):
            raise StartupError('Cannot identify the running account service. Stop it before switching hosting modes.') from None
        labels = dict(item.split('=', 1) for item in labels.split(',') if '=' in item)
        if labels.get('com.docker.compose.project') != 'argus-soc-local' or labels.get('com.docker.compose.service') != 'relay':
            raise StartupError('Another running service uses this account volume. Stop that relay first; '
                               'then retry with the same volume. Do not delete it.')
    private = ROOT / 'data/soc-forwarded'
    private.mkdir(parents=True, exist_ok=True)
    config = private / 'host.env'
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(f'SOC_FORWARDED_URL={url}\nSOC_FORWARD_PORT={port}\nSOC_ACCOUNTS_VOLUME={accounts_volume}\n')
    compose = [docker, 'compose', '--env-file', str(config), '-f', 'soc/compose.forwarded.yml']
    if execute(compose + ['config', '--quiet'], environment).returncode:
        raise StartupError('Docker Compose rejected the forwarding configuration. Update Compose and retry.')
    progress('Building the relay…')
    if execute(compose + ['build', 'relay'], environment).returncode:
        raise StartupError('The relay image could not build. Existing accounts and running services were not changed.')
    # Opening SQLite with mode=ro cannot create a new database or reset accounts.
    if execute(compose + ['run', '--rm', '--no-deps', '-T', 'relay', 'python', '-c', ACCOUNT_CHECK], environment).returncode:
        raise StartupError('The selected account volume has no readable active SOC accounts. '
                           'Choose the correct existing volume or finish local account setup first.')
    progress('Switching the existing stack to forwarding mode…')
    if execute(compose + ['up', '-d', 'relay', 'https'], environment).returncode:
        raise StartupError('Forwarded stack startup failed. Inspect docker compose --env-file '
                           'data/soc-forwarded/host.env -f soc/compose.forwarded.yml logs --tail 50.')
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='HTTPS Forwarded Address copied from the VS Code Ports view')
    parser.add_argument('--port', type=int, default=8765, help='host loopback port to forward (default: 8765)')
    parser.add_argument('--accounts-volume', default=DEFAULT_VOLUME, help='existing Docker account volume; never recreated or seeded')
    args = parser.parse_args()
    try:
        if not 1024 <= args.port <= 65535:
            raise ValueError('Use a local port between 1024 and 65535')
        url = args.url
        if not url:
            print(f'In VS Code: Ports → Forward a Port → {args.port} → Port Visibility: Public.')
            print('Copy its HTTPS Forwarded Address. It starts responding after this setup finishes.')
            with forwarding_listener(args.port):
                url = input('Paste the forwarded HTTPS address: ').strip()
        url = start(url, args.port, args.accounts_volume)
        print(f'Host port: 127.0.0.1:{args.port} (HTTP inside the tunnel; public link is HTTPS).')
        print('Checking the public forwarded link…')
        error = None
        for attempt in range(6):
            try:
                health = SOCClient(url).request('GET', '/healthz')
                if isinstance(health, dict) and health.get('ready') is True and health.get('service') == 'argus-soc' and health.get('protocol') == 2:
                    print('PASS: forwarded HTTPS reaches the shared account relay.')
                    error = None
                    break
                error = 'The forwarded address did not return the SOC health response.'
            except ClientError as problem:
                error = str(problem)
            if attempt < 5:
                time.sleep(2)
        if error:
            print(f'Stack started, but the public link is not ready: {error}', file=sys.stderr)
            print('Keep VS Code open; forward the host port with protocol HTTP and visibility Public.', file=sys.stderr)
            return 1
        print(f'On BOTH devices: open Argus SOC sign-in and use {url}')
        print('Use your existing usernames/passwords. Do not start another local server on the second device.')
        print('Create/join one Team session, start secure chat, then compare every peer code before chatting or pinging.')
        return 0
    except (ValueError, StartupError, EOFError, KeyboardInterrupt) as error:
        print(f'Hosting setup stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
