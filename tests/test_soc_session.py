"""Remembered SOC sign-in stays in the keychain, holds no password and fails safe."""
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from argus import soc_session


class FakeKeychain:
    def __init__(self, broken=False):
        self.items = {}
        self.broken = broken

    def check(self):
        if self.broken:
            raise RuntimeError("No recommended backend was available")

    def set_password(self, service, account, value):
        self.check()
        self.items[service, account] = value

    def get_password(self, service, account):
        self.check()
        return self.items.get((service, account))

    def delete_password(self, service, account):
        self.check()
        del self.items[service, account]


def client():
    return SimpleNamespace(url="https://soc.example.invalid", token="synthetic-token-" + "x" * 27,
                           user={"username": "marwan"}, ca_file=None)


class RememberedSignInTests(unittest.TestCase):
    def test_saves_loads_and_forgets_only_the_token(self):
        keychain = FakeKeychain()
        with patch.dict(sys.modules, {"keyring": keychain}):
            self.assertIsNone(soc_session.load())
            self.assertTrue(soc_session.save(client()))
            saved = soc_session.load()
            self.assertEqual((saved["url"], saved["token"], saved["username"]),
                             ("https://soc.example.invalid", client().token, "marwan"))
            stored = json.loads(keychain.items[soc_session.SERVICE, soc_session.ACCOUNT])
            self.assertEqual(set(stored), {"url", "token", "username", "ca_file"})
            soc_session.forget()
            self.assertIsNone(soc_session.load())
            soc_session.forget()  # Forgetting twice is harmless.

    def test_missing_or_broken_keychain_means_sign_in_normally(self):
        for keychain in (None, FakeKeychain(broken=True)):
            with patch.dict(sys.modules, {"keyring": keychain}):
                self.assertFalse(soc_session.save(client()))
                self.assertIsNone(soc_session.load())
                soc_session.forget()

    def test_unreadable_entry_is_ignored(self):
        keychain = FakeKeychain()
        for value in ("not json", json.dumps(["list"]), json.dumps({"url": "https://soc.example.invalid"})):
            keychain.items[soc_session.SERVICE, soc_session.ACCOUNT] = value
            with patch.dict(sys.modules, {"keyring": keychain}):
                self.assertIsNone(soc_session.load())


if __name__ == "__main__":
    unittest.main()
