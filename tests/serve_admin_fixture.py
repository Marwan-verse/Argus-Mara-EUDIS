"""Isolated browser-test SOC; synthetic credentials and a disposable database."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from argus.collab_server import Config, SERVICE, create_app


def main():
    with tempfile.TemporaryDirectory(prefix="argus-admin-browser-") as directory:
        app = create_app(Config(Path(directory) / "accounts.sqlite3", origin="http://127.0.0.1:8082", allow_loopback_http=True))
        store = app[SERVICE].store
        hashed = store.hasher.hash("synthetic-browser-password-42")
        store.create_user("testadmin", hashed, ["intelligence"], admin=True)
        store.create_user("testoperator", hashed, ["user"])
        store.create_user("applicant", hashed, [])
        web.run_app(app, host="127.0.0.1", port=8082, access_log=None, print=None)


if __name__ == "__main__":
    main()
