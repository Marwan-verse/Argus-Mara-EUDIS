"""The docked incident board groups, labels and records decisions without sending anything."""
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from argus.levels import RANK
from desktop_alerts import STYLE
from argus.live_client import LiveState


class DesktopAlertBoardTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.attributes('-alpha', 0)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        with patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': ''}):
            self.app = ArgusApp(self.root, *load_demo())
        self.app.ais_tracker.cache_path = None
        self.app.ais_tracker.state = LiveState()
        self.root.update()
        self.board = self.app.alert_board

    def tearDown(self):
        if hasattr(self, 'app'):
            self.root.update()
            self.assertEqual(self.errors, [])
            self.app.close()

    def packed_cards(self):
        cards = {card['frame']: key for key, card in self.board.cards.items()}
        return [cards[widget] for widget in self.board.list.pack_slaves() if widget in cards]

    def map_tags(self, prefix):
        return {tag for item in self.app.map.find_all() for tag in self.app.map.gettags(item) if tag.startswith(prefix)}

    def actions(self):
        return [widget.cget('text') for widget in self.board.dialog.actions.winfo_children()]

    def flags(self, key):
        return [label.cget('text') for label in self.board.cards[key]['flag_labels'] if label.winfo_manager()]

    def test_list_shows_incidents_by_level_and_watches_low(self):
        app, board = self.app, self.board
        self.assertTrue(app.alerts_panel.winfo_ismapped())
        self.assertGreaterEqual(app.chart_host.winfo_x(), app.alerts_panel.winfo_x() + app.alerts_panel.winfo_width())
        order = self.packed_cards()
        self.assertEqual(len(order), 22)  # Medium and above: one incident card each; Low is folded away
        ranks = [RANK[board.by_id[key]['assessment']['level']] for key in order]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        # SIM-06, SIM-44 and SIM-48 are raised one level: no responder reaches them before their line ETA.
        self.assertEqual([board.tiles[f'{level}-count'].cget('text') for level in ('critical', 'high', 'medium', 'low')],
                         ['6', '6', '10', '27'])
        self.assertEqual(board.cards['SIM-01']['stripe'].cget('bg'), STYLE['critical'][0])
        self.assertIn('In corridor', board.cards['SIM-01']['eta'].cget('text'))
        self.assertIn('22 new', app.alert_counts_label.cget('text'))
        self.assertEqual(board.summary.cget('text'), '22 open · 0 escalated')
        self.assertEqual(self.flags('SIM-45'), ['AIS spoofing?'])
        self.assertEqual(len(self.map_tags('sim-alert:')), len(board.items))
        badge = next(item for item in app.map.find_withtag('sim-badge') if app.map.type(item) == 'text')
        self.assertIn('SIMULATED', app.map.itemcget(badge, 'text'))
        board.set_filter('critical')
        self.assertEqual(len(self.packed_cards()), 6)
        self.assertEqual(len(self.map_tags('sim-alert:')), 6)
        board.set_filter('critical')
        self.assertIsNone(board.level_filter)
        board.set_filter('low')
        self.assertIn('SIM-40', self.packed_cards())
        self.assertEqual(len(self.packed_cards()), 27)
        self.assertEqual(self.flags('SIM-40'), ['Small craft · capped Low'])
        board.set_filter(None)
        board.toggle_watching()
        self.assertEqual(len(self.packed_cards()), len(board.items))
        board.sort_mode.set('Time to asset')
        board.relayout(top=True)
        self.assertEqual(len(self.packed_cards()), len(board.items))

    def test_review_escalate_withdraw_and_reject_go_through_incidents(self):
        app, board, dialog = self.app, self.board, self.board.dialog
        board.open('SIM-01')
        self.root.update()
        self.assertTrue(dialog.frame.winfo_ismapped())
        self.assertEqual(board.status('SIM-01'), 'Reviewed')
        self.assertEqual(board.incident('SIM-01')['status_log'][-1]['status'], 'Reviewed')
        self.assertIn('INC-SIM-01-1', dialog.score.cget('text'))
        self.assertIn('sim-selected', {tag for item in app.map.find_all() for tag in app.map.gettags(item)})
        dialog.open_form('escalate')
        dialog.choice.set('Irish Coast Guard (MRCC)')
        dialog.note.insert(0, 'Anchor still down')
        dialog.confirm()
        self.assertEqual(board.status('SIM-01'), 'Escalated')
        self.assertEqual(board.recipients['SIM-01'], 'Irish Coast Guard (MRCC)')
        self.assertIn('Escalated · Irish Coast Guard (MRCC)', board.cards['SIM-01']['status'].cget('text'))
        self.assertEqual(board.history['SIM-01'][-1][1], 'Escalated to Irish Coast Guard (MRCC). Note: Anchor still down')
        self.assertIn('1 escalated', app.alert_counts_label.cget('text'))
        self.assertIn('Withdraw', self.actions())
        board.withdraw('SIM-01')
        self.assertEqual(board.status('SIM-01'), 'Reviewed')
        self.assertIsNone(app.approved)

        board.open('SIM-41')
        dialog.open_form('reject')
        dialog.choice.set('Known benign activity')
        dialog.confirm()
        self.assertEqual(board.status('SIM-41'), 'Rejected')
        self.assertEqual(board.incident('SIM-41')['status_reason'], 'Known benign activity')
        self.assertNotIn('SIM-41', self.packed_cards())
        self.assertNotIn('sim-alert:SIM-41', self.map_tags('sim-alert:'))
        self.assertEqual(self.actions(), ['Show on map'])
        board.toggle_closed()
        self.assertIn('SIM-41', self.packed_cards())

        board.open('SIM-40')
        self.assertEqual(board.status('SIM-40'), 'Watching')
        self.assertEqual(self.actions(), ['Show on map'])
        with patch.object(app, 'require_tool', return_value=False):
            board.decide('SIM-02', 'Acknowledged', 'Acknowledged')
        self.assertEqual(board.status('SIM-02'), 'New')

        dialog.escape(SimpleNamespace(widget=self.root))
        self.assertFalse(dialog.visible)
        self.assertIsNone(board.selected)
        board.restart()
        self.assertEqual(board.status('SIM-01'), 'New')
        self.assertEqual(board.status('SIM-41'), 'New')
        self.assertEqual(board.replay.decisions, [])
        self.assertEqual([text for _t, text in board.history['SIM-01']], ['Incident INC-SIM-01-1 opened at Critical'])

    def test_exercise_incident_shares_review_status_and_map_click_opens_it(self):
        app, board, tools = self.app, self.board, self.app.tools
        exercise = next(item for item in board.items if item.get('exercise'))
        board.open(exercise['id'])
        self.assertEqual(tools.alert_statuses[exercise['id']].get(), 'Reviewed')
        self.assertEqual(board.incident(exercise['id'])['id'], 'INC-999000001-1')
        board.decide(exercise['id'], 'Acknowledged', 'Acknowledged, watching')
        self.assertEqual(tools.alert_statuses[exercise['id']].get(), 'Acknowledged')
        self.assertIn('1 acknowledged', app.alert_counts_label.cget('text'))
        tools.set_alert_status(exercise['id'], 'Reviewed')
        self.assertEqual(board.status(exercise['id']), 'Reviewed')
        board.dialog.close()

        app.fit_ireland()
        self.root.update()
        marker = next(item for item in app.map.find_withtag('sim-alert:SIM-02')
                      if app.map.type(item) in ('oval', 'polygon'))
        left, top, right, bottom = app.map.bbox(marker)
        app._inspect_map_item(SimpleNamespace(x=(left + right) / 2, y=(top + bottom) / 2))
        self.assertEqual(board.selected, 'SIM-02')
        self.assertTrue(board.dialog.visible)

    def test_review_window_explains_the_level(self):
        board, dialog = self.board, self.board.dialog

        def texts():
            found, stack = [], list(dialog.body.winfo_children())
            while stack:
                widget = stack.pop(0)
                stack.extend(widget.winfo_children())
                if isinstance(widget, tk.Label):
                    found.append(widget.cget('text'))
            return found

        board.set_filter('low')
        self.assertEqual(self.flags('SIM-47'), [])  # a lone GPS glitch is not flagged as spoofing
        board.set_filter(None)
        board.open('SIM-46')
        shown = texts()
        for heading in ('WHY THIS LEVEL', 'RULES APPLIED', 'THREATENED LINE', 'SMALL VESSEL',
                        'FINDINGS BY DETECTOR', 'DATA LABELS'):
            self.assertIn(heading, shown)
        self.assertIn('B2 I2 P3 A2 C0 = 9', shown)
        self.assertIn('B  Behaviour', shown)
        self.assertIn('nothing observed', shown)
        self.assertIn('AIS spoofing check', shown)
        for tag in ('SIMULATED', 'REAL', 'ASSUMPTION', 'ILLUSTRATIVE'):
            self.assertIn(tag, shown)
        self.assertIn('AIS spoofing?   Small craft · cap lifted', dialog.flags.cget('text'))
        dialog.body._parent_canvas.yview_moveto(1)
        board.open('SIM-44')
        self.assertEqual(dialog.body._parent_canvas.yview()[0], 0)
        self.assertTrue(any(text.startswith('Also named: Gas interconnector IC2') for text in texts()))

    def test_incidents_follow_the_replay_clock_and_a_card_click_centres_the_map(self):
        app, board = self.app, self.board
        start = app.alert['t']
        self.assertEqual(board.clock.cget('text'), 'T+01:30')
        app.position_s = start - 40 * 60  # before the exercise alert and before some contacts were raised
        board.follow()
        self.assertEqual(board.clock.cget('text'), 'T+00:50')
        self.assertEqual(board.status('A1'), 'Watching')
        self.assertEqual(board.group('SIM-07'), 'hidden')
        self.assertNotIn('SIM-07', self.packed_cards())
        self.assertNotIn('sim-alert:SIM-07', self.map_tags('sim-alert:'))
        app.position_s = start
        board.follow()
        self.assertEqual(board.status('A1'), 'New')
        self.assertIn('SIM-07', self.packed_cards())
        app.position_s = start + 70 * 60  # SIM-48 crossed its line at +35 min and has been quiet since
        board.follow()
        self.assertEqual(board.group('SIM-48'), 'quiet')
        self.assertIn('Quiet 30 min · close?', self.flags('SIM-48'))
        self.assertEqual(board.history['SIM-48'][-1][1], 'Quiet 30 min below Medium: close?')
        self.assertIn(board.stamp(board.replay.now), app.map_status_label.cget('text'))

        app.fit_ireland()
        self.root.update()
        board.open('SIM-02', centre=True)
        self.root.update()
        item = board.by_id['SIM-02']
        x, y = app._project(item['lat'], item['lon'])
        width, height = app._map_size
        self.assertLess(abs(y - (height / 2 - 20)), 40)
        self.assertLess(x, width - board.dialog.covered_width())

    def test_countdown_raises_an_incident_and_the_board_can_hide(self):
        # Four minutes on, CORRIB MIST's ETA is too short for any responder, so it is raised one level.
        app, board = self.app, self.board
        board.decide('SIM-07', 'Reviewed', 'Reviewed')
        app.position_s += 4 * 60
        board.follow()
        self.assertEqual(board.by_id['SIM-07']['assessment']['level'], 'critical')
        self.assertEqual(board.tiles['critical-count'].cget('text'), '8')
        self.assertIn('CORRIB MIST review again', app.map_status_label.cget('text'))
        self.assertEqual(self.packed_cards()[0], 'SIM-07')  # review again sorts first in its level
        self.assertIn('⚠ Review again', self.flags('SIM-07'))
        self.assertEqual([text for _stamp, text in board.history['SIM-07']][-2:],
                         ['Level raised to Critical', 'Level rose after review: review again'])
        self.assertRegex(board.cards['SIM-07']['eta'].cget('text'), r'^ETA \d\d:\d\d$')
        width = app.map.winfo_width()
        app.tools.toggle_alerts()
        self.root.update()
        self.assertFalse(app.alerts_panel.winfo_ismapped())
        self.assertGreater(app.map.winfo_width(), width)
        app.tools.toggle_alerts()
        self.root.update()
        self.assertTrue(app.alerts_panel.winfo_ismapped())

if __name__ == '__main__':
    unittest.main()
