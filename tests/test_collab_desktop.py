"""Native SOC integration: group tools, admin forms and existing ping reuse."""
import os
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk

from run_gui import ArgusApp, load_demo


class FakeClient:
    def __init__(self, admin=False):
        self.user = {"id": "own", "username": "analyst", "admin": admin,
                     "groups": ["user"], "permissions": ["map.view", "chat", "ping", "contact.share"]}
        self.url = "https://soc.example.invalid"
        self.room = {"members": [{"user_id": "own", "username": "analyst"}, {"user_id": "peer", "username": "colleague"}], "confirmed": ["own", "peer"]}
        self.cipher = SimpleNamespace(verified=True, room_id="room", safety_code="ABCD " * 8)
        self.code = None
        self.calls = []

    def poll(self):
        return []

    def logout(self):
        pass

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if method == "GET" and path == "/v1/admin":
            return {"users": [{"id": "other", "username": "bob", "groups": ["user"], "disabled": False}],
                    "groups": [{"name": "user", "permissions": ["chat"]}, {"name": "intelligence", "permissions": ["evidence.share"]}],
                    "available_permissions": ["map.view", "chat", "ping", "contact.share", "evidence.share", "alert.review", "response.review"]}
        return {"ok": True}


class DesktopSOCTests(unittest.TestCase):
    def setUp(self):
        self.root = ctk.CTk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.client = FakeClient(admin=True)
        with patch.dict(os.environ, {"ARGUS_AIS_AUTOCONNECT": "0", "ARGUS_UI_PREFERENCES": ""}):
            self.app = ArgusApp(self.root, *load_demo(), soc_client=self.client)
        self.app.ais_tracker.cache_path = None

    def tearDown(self):
        self.app.close()
        self.assertEqual(self.errors, [])

    def pump(self):
        # Network workers emit results; only the Tk thread handles widgets.
        for _ in range(20):
            self.root.update()
            self.app.soc.tick()
            if self.app.soc.pending <= 1:
                time.sleep(.01)
        self.root.update()

    def test_group_tools_and_existing_ping_receive_does_not_echo(self):
        self.assertTrue(self.app.allowed("ping"))
        self.assertFalse(self.app.allowed("evidence.share"))
        with patch("run_gui.messagebox.showinfo"):
            self.app.open_window("evidence")
            self.app.review_response()
        self.assertNotIn("evidence", self.app._panel_widgets)
        self.assertNotIn("decision", self.app._panel_widgets)
        self.app.soc.send_message = Mock()
        self.app._place_map_ping((53.35, -6.25))
        self.app.soc.send_message.assert_called_once_with("ping", {"lat": 53.35, "lon": -6.25})
        self.app.soc.send_message.reset_mock()
        self.app.soc.receive([{"kind": "ping", "payload": {"lat": 54, "lon": -7}}])
        self.assertEqual(self.app._map_ping, (54, -7))
        self.app.soc.send_message.assert_not_called()
        self.assertIsNone(self.app.approved)
        self.app.soc_online = False
        self.assertFalse(self.app.allowed("ping"))

    def test_soc_window_and_administrator_group_form(self):
        self.app.soc.open()
        self.app.soc.window.withdraw()
        self.pump()
        soc = self.app.soc
        self.assertEqual(str(soc.send_button.cget("state")), "normal")
        self.assertIn("colleague", soc.safety_label.cget("text"))
        self.assertEqual(soc.kind_selector.cget("values"), ("chat", "contact"))
        soc.group_selector.set("watch_team")
        soc.perm_vars["map.view"].set(True)
        soc.perm_vars["ping"].set(True)
        soc.save_group()
        self.pump()
        self.assertTrue(any(method == "PUT" and path == "/v1/admin/groups/watch_team" and data["permissions"] == ["map.view", "ping"] for method, path, data in self.client.calls))


if __name__ == "__main__":
    unittest.main()
