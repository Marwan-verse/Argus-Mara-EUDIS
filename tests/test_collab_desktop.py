"""Native SOC integration: group tools, admin forms and existing ping reuse."""
import os
import time
import tkinter as tk
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
        self.room = {"members": [{"user_id": "own", "username": "analyst", 'groups': ['intelligence']}, {"user_id": "peer", "username": "colleague", 'groups': ['user']}], "confirmed": ["own", "peer"], 'locked': True, 'host_id': 'own', 'permissions': ['map.view', 'chat', 'ping', 'contact.share']}
        self.cipher = SimpleNamespace(verified=True, room_id="room", safety_code="ABCD " * 8, safety_codes={'peer': 'ABCD ' * 8})
        self.code = None
        self.calls = []

    def poll(self):
        return []

    def logout(self):
        pass

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if method == "GET" and path == "/v1/admin":
            return {"users": [{"id": "other", "username": "bob", "groups": ["user"], "disabled": False},
                              {"id": "new", "username": "newcomer", "groups": [], "disabled": False, "admin": False}],
                    "groups": [{"name": "user", "permissions": ["chat"]}, {"name": "intelligence", "permissions": ["evidence.share"]}],
                    "available_permissions": ["map.view", "chat", "ping", "contact.share", "evidence.share", "alert.review", "response.review"]}
        return {"ok": True}


class DesktopSOCTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f'Native display unavailable: {error}')
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
        self.assertIn('Secure chat is ready', soc.stage_label.cget('text'))
        self.assertIn('Contacts', soc.tools_label.cget('text'))
        self.assertFalse(soc.evidence_button.winfo_manager())
        soc.group_selector.set("watch_team")
        soc.perm_vars["map.view"].set(True)
        soc.perm_vars["ping"].set(True)
        soc.save_group()
        self.pump()
        self.assertTrue(any(method == "PUT" and path == "/v1/admin/groups/watch_team" and data["permissions"] == ["map.view", "ping"] for method, path, data in self.client.calls))
        self.assertIn("Waiting for approval: newcomer.", soc.pending_label.cget("text"))

    def test_short_invite_copy_and_lobby_actions(self):
        self.client.room.update(locked=False, confirmed=[], invitation_expires=time.time()+600)
        self.client.cipher.room_id = None
        self.client.code = 'ABCDEFGH'
        self.app.soc.open()
        self.app.soc.window.withdraw()
        self.pump()
        soc = self.app.soc
        self.assertEqual(soc.invite_label.cget('text'), 'ABCD-EFGH')
        soc.copy_invite()
        self.assertEqual(soc.window.clipboard_get(), 'ABCD-EFGH')
        self.assertEqual(soc.send_button.cget('state'), 'disabled')
        self.assertTrue(soc.start_button.winfo_manager())
        self.assertEqual(soc.group.get(), 'Team session (all groups)')

    def test_typed_code_verifies_peer_and_wrong_code_does_not(self):
        from argus.collab_crypto import RoomCipher
        own, peer = RoomCipher(), RoomCipher()
        members = [{'user_id': 'own', 'username': 'analyst', 'public_key': own.public_key},
                   {'user_id': 'peer', 'username': 'colleague', 'public_key': peer.public_key}]
        own.establish('room', 'own', members)
        peer.establish('room', 'peer', members)
        self.client.cipher = own
        self.client.room.update(room_id='room', confirmed=[])
        self.client.confirm = Mock()
        self.app.soc.open()
        self.app.soc.window.withdraw()
        self.pump()
        soc = self.app.soc
        soc.compare_peer('peer')
        from desktop_soc import shareable_code
        # Opening the dialog copies one's own code, labelled with both names.
        self.assertEqual(self.root.clipboard_get(), shareable_code('analyst', 'colleague', own.safety_codes['peer']))
        soc.verify_paste()  # Pasting that back is one's own code, not the colleague's.
        soc.verify_check()
        self.assertIn('your own code', soc.verify_problem.cget('text'))
        soc.verify_entry.delete(0, 'end')
        soc.verify_entry.insert(0, shareable_code('someone', 'analyst', peer.safety_codes['own']))
        soc.verify_check()
        self.assertIn('not from colleague to you', soc.verify_problem.cget('text'))
        self.assertEqual(own.verified_peers, set())
        read_aloud = peer.safety_codes['own']
        soc.verify_entry.delete(0, 'end')
        soc.verify_entry.insert(0, ('B' if read_aloud[0] == 'A' else 'A') + read_aloud[1:])
        soc.verify_check()
        self.assertIn('codes differ', soc.verify_problem.cget('text'))
        self.assertNotIn('peer', soc.verified_peers)
        self.assertEqual(own.verified_peers, set())
        self.client.confirm.assert_not_called()
        soc.verify_entry.delete(0, 'end')
        # The colleague's own copied text, sent through another app and pasted here.
        soc.verify_entry.insert(0, shareable_code('colleague', 'analyst', read_aloud))
        soc.verify_check()
        self.pump()
        self.assertIn('peer', soc.verified_peers)
        self.assertEqual(own.verified_peers, {'peer'})
        self.client.confirm.assert_called_once()
        self.assertFalse(soc.verify_window.winfo_exists())

    def test_closing_keeps_a_remembered_sign_in_but_leaves_the_session(self):
        self.client.remember = True
        self.client.leave, self.client.logout = Mock(), Mock()
        soc = self.app.soc
        soc.close()
        soc.executor.shutdown(wait=True)
        self.client.leave.assert_called_once()
        self.client.logout.assert_not_called()
        soc.client = None  # The app closes again in tearDown.

    def test_sign_out_forgets_the_saved_sign_in_and_revokes_it(self):
        self.client.remember = True
        self.client.logout = Mock()
        with patch('desktop_soc.messagebox.askyesno', return_value=True), \
                patch('desktop_soc.soc_session.forget') as forget, patch.object(self.app, 'close') as close:
            self.app.soc.sign_out()
        forget.assert_called_once()
        close.assert_called_once()
        self.assertFalse(self.client.remember)
        soc = self.app.soc
        soc.close()
        soc.executor.shutdown(wait=True)
        self.client.logout.assert_called_once()
        soc.client = None

    def test_revoked_access_forgets_the_saved_sign_in(self):
        from argus.collab_client import ClientError
        soc = self.app.soc
        soc.pending += 1
        soc.events.put((None, None, ClientError('Sign in required', 401), True))
        with patch('desktop_soc.messagebox.showinfo'), patch('desktop_soc.soc_session.forget') as forget, \
                patch.object(self.app, 'close') as close:
            soc.tick()
        forget.assert_called_once()
        close.assert_called_once()

    def test_chat_groups_people_and_shows_pings_contacts_and_evidence(self):
        import json
        soc = self.app.soc
        soc.open()
        soc.window.withdraw()
        self.pump()
        self.assertIn('No messages yet', soc.chat.get('1.0', 'end'))
        contact = {"mmsi": 250001234, "name": "SEA EAGLE", "lat": 53.4, "lon": -6.1, "sog_kn": 11.2,
                   "cog_deg": 284, "received_utc": "2026-10-15T12:01:02Z", "label": "real"}
        soc.receive([{"kind": "chat", "payload": {"text": "Anchor still down"}, "sender": "colleague"},
                     {"kind": "chat", "payload": {"text": "Watching it"}, "sender": "colleague"},
                     {"kind": "ping", "payload": {"lat": 53.35, "lon": -6.25}, "sender": "colleague"},
                     {"kind": "contact", "payload": {"text": json.dumps(contact)}, "sender": "colleague"},
                     {"kind": "evidence", "payload": {"text": "Scenario: exercise\nREVIEW CUES"}, "sender": "colleague"}])
        soc.record('You', True, 'ping', {'lat': 53.0, 'lon': -6.0})
        soc.render()
        shown = soc.chat.get('1.0', 'end')
        self.assertEqual(shown.count('colleague'), 1)  # One name line for messages close together.
        self.assertIn('UTC', shown)
        self.assertIn('Anchor still down\nWatching it\n', shown)
        self.assertIn('Ping  53.3500°N, 6.2500°W   Show on map', shown)
        self.assertIn('Contact  SEA EAGLE · MMSI 250001234 · 53.4000°N, 6.1000°W · 11.2 kn · 284° · fix 12:01 UTC · real',
                      shown)
        self.assertIn('Evidence summary\nScenario: exercise\nREVIEW CUES', shown)
        self.assertIn('You', shown)
        for raw in ('{"mmsi"', "{'lat'"):
            self.assertNotIn(raw, shown)
        with patch.object(self.app, '_change_map_center') as center:
            soc.show_point((53.35, -6.25))
        center.assert_called_once_with((53.35, -6.25))

    def test_empty_draft_and_enter_do_not_submit(self):
        self.app.soc.open()
        self.app.soc.window.withdraw()
        self.pump()
        soc = self.app.soc
        soc.send_message = Mock()
        soc.send_text()
        soc.send_message.assert_not_called()
        soc.message.insert('1.0', 'hello')
        self.assertIsNone(soc.enter_message(SimpleNamespace(state=1)))
        soc.send_message.assert_not_called()
        self.assertEqual(soc.enter_message(SimpleNamespace(state=0)), 'break')
        self.assertEqual(soc.send_message.call_args.args[:2], ('chat', {'text': 'hello'}))
        self.assertEqual(soc.message.get('1.0', 'end').strip(), 'hello')
        soc.send_message.call_args.args[2]()
        self.assertEqual(soc.message.get('1.0', 'end').strip(), '')


class ChatFormattingTests(unittest.TestCase):
    def test_contact_summary_keeps_only_real_values(self):
        import json
        from desktop_soc_view import contact_summary
        self.assertEqual(contact_summary('plain text'), ('plain text', None))
        self.assertEqual(contact_summary('[1, 2]'), ('[1, 2]', None))
        weird = {'name': 'X', 'lat': 95, 'lon': 0, 'sog_kn': True, 'cog_deg': float('nan'), 'received_utc': 'soon'}
        self.assertEqual(contact_summary(json.dumps(weird)), ('X', None))


if __name__ == "__main__":
    unittest.main()
