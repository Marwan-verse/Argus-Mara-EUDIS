"""Check public source candidates for credential patterns without printing secret values.

Default: tracked and non-ignored new files. --history also checks every reachable Git
blob, including branches/tags. This is a heuristic guard, not a complete security audit.
"""
import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'provider credential': re.compile(rb'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|sb_(?:secret|publishable)_[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|tx-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[0-9A-Za-z-]{20,})'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'credential URL': re.compile(rb'(?:postgres(?:ql)?|https?)://[^\s/\x22\x27]+:[^\s/@\x22\x27]+@'),
    'JWT credential': re.compile(rb'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'),
}


def findings(data, name):
    if b'\0' in data[:8192]:
        return []  # Binary assets need separate manual review.
    result = []
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            # Explicitly synthetic format/security regression fixtures; no live access.
            if name.startswith('tests/') and kind == 'credential URL':
                continue
            if (name == 'tests/test_supabase_ais.py' and kind == 'JWT credential'
                    and match.group().endswith(b'.c2lnbmF0dXJl')):
                continue
            result.append((kind, data.count(b'\n', 0, match.start()) + 1))
    return result


def private_path(name):
    p = Path(name)
    return (name.startswith(('data/', '.venv/', 'node_modules/', '.secrets/'))
            or name == 'recorder/.apikey'
            or (p.name.startswith('.env') and not p.name.endswith('.example'))
            or p.suffix.lower() in {'.pem', '.key', '.p12', '.pfx', '.sqlite', '.sqlite3', '.db', '.apikey'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true')
    args = parser.parse_args()
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    failed, checked = False, 0
    for name in sorted(set(names.decode('utf-8').split('\0')) - {''}):
        path = ROOT/name
        if private_path(name):
            print(f'{name}: private file must not be published')
            failed = True
        if not path.is_file():
            continue
        checked += 1
        for kind, line in findings(path.read_bytes(), name):
            print(f'{name}:{line}: {kind} (value withheld)')
            failed = True
    print(f'Checked {checked} public source candidates.')
    if args.history:
        objects = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=ROOT).splitlines()
        process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        count = 0
        try:
            for entry in objects:
                oid, _, name = entry.partition(b' ')
                process.stdin.write(oid+b'\n')
                process.stdin.flush()
                header = process.stdout.readline().split()
                if len(header) != 3:
                    continue
                data = process.stdout.read(int(header[2]))
                process.stdout.read(1)
                if header[1] != b'blob':
                    continue
                count += 1
                path = name.decode('utf-8', errors='replace')
                for kind, line in findings(data, path):
                    print(f'history {oid.decode()[:12]} {path}:{line}: {kind} (value withheld)')
                    failed = True
        finally:
            process.stdin.close()
            process.wait()
        print(f'Checked {count} historical blobs; no history was modified.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
