"""The docked alert board sorts, labels and records decisions without sending anything."""
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from argus.levels import RANK
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

    def test_list_is_docked_sorted_and_labelled(self):
        app, board = self.app, self.board
        self.assertTrue(app.alerts_panel.winfo_ismapped())
        self.assertGreaterEqual(app.chart_host.winfo_x(), app.alerts_panel.winfo_x() + app.alerts_panel.winfo_width())
        order = self.packed_cards()
        self.assertEqual(len(order), len(board.items))
        ranks = [RANK[board.by_id[key]['assessment']['level']] for key in order]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        self.assertEqual(board.tiles['critical-count'].cget('text'), '3')
        self.assertEqual(board.tiles['low-count'].cget('text'), '24')
        self.assertEqual(board.cards['SIM-01']['code'].cget('text'), 'CRIT')
        self.assertEqual(board.cards['SIM-01']['score'].cget('text'), '10')
        self.assertIn('40 new', app.alert_counts_label.cget('text'))
        self.assertEqual(len(self.map_tags('sim-alert:')), len(board.items))
        badge = next(item for item in app.map.find_withtag('sim-badge') if app.map.type(item) == 'text')
        self.assertIn('SIMULATED', app.map.itemcget(badge, 'text'))
        board.set_filter('critical')
        self.assertTrue(all(board.by_id[key]['assessment']['level'] == 'critical' for key in self.packed_cards()))
        self.assertEqual(len(self.map_tags('sim-alert:')), 3)
        board.set_filter('critical')
        self.assertIsNone(board.level_filter)
        board.sort_mode.set('Time to asset')
        board.relayout(top=True)
        self.assertEqual(len(self.packed_cards()), len(board.items))

    def test_review_escalate_reject_and_reopen_stay_local(self):
        app, board, dialog = self.app, self.board, self.board.dialog
        board.open('SIM-01')
        self.root.update()
        self.assertTrue(dialog.frame.winfo_ismapped())
        self.assertEqual(board.status('SIM-01'), 'Reviewed')
        self.assertIn('sim-selected', {tag for item in app.map.find_all() for tag in app.map.gettags(item)})
        dialog.open_form('escalate')
        dialog.choice.set('Irish Coast Guard (MRCC)')
        dialog.note.insert(0, 'Anchor still down')
        dialog.confirm()
        self.assertEqual(board.status('SIM-01'), 'Escalated')
        self.assertEqual(board.decisions['SIM-01']['to'], 'Irish Coast Guard (MRCC)')
        self.assertEqual(board.cards['SIM-01']['status'].cget('text'), 'Escalated')
        self.assertEqual(board.history['SIM-01'][-1][1], 'Escalated to Irish Coast Guard (MRCC). Note: Anchor still down')
        self.assertIn('1 escalated', app.alert_counts_label.cget('text'))
        self.assertIsNone(app.approved)

        board.open('SIM-21')
        dialog.open_form('reject')
        dialog.choice.set('Known benign activity')
        dialog.confirm()
        self.assertEqual(board.status('SIM-21'), 'Rejected')
        self.assertNotIn('SIM-21', self.packed_cards())
        self.assertNotIn('sim-alert:SIM-21', self.map_tags('sim-alert:'))
        board.toggle_closed()
        self.assertIn('SIM-21', self.packed_cards())
        board.reopen('SIM-21')
        self.assertEqual(board.status('SIM-21'), 'Reviewed')
        self.assertIn('sim-alert:SIM-21', self.map_tags('sim-alert:'))

        dialog.escape(SimpleNamespace(widget=self.root))
        self.assertFalse(dialog.visible)
        self.assertIsNone(board.selected)
        board.restart()
        self.assertEqual(board.status('SIM-01'), 'New')
        self.assertEqual(board.history, {})

    def test_exercise_item_shares_review_status_and_map_click_opens_contacts(self):
        app, board, tools = self.app, self.board, self.app.tools
        exercise = next(item for item in board.items if item.get('exercise'))
        board.open(exercise['id'])
        self.assertEqual(tools.alert_statuses[exercise['id']].get(), 'Reviewed')
        board.decide(exercise['id'], 'Acknowledged', 'Acknowledged, watching')
        self.assertEqual(tools.alert_statuses[exercise['id']].get(), 'Acknowledged')
        self.assertIn('1 acknowledged', app.alert_counts_label.cget('text'))
        board.dialog.close()

        app.fit_ireland()
        # A country-wide view on a small runner display can overlap callouts.
        # Inspect the actual marker after centering/zooming to this contact.
        contact = board.by_id['SIM-02']
        app._change_map_center((contact['lat'], contact['lon']))
        app._zoom_by(3)
        self.root.update()
        marker = next(item for item in app.map.find_withtag('sim-alert:SIM-02')
                      if app.map.type(item) in ('oval', 'polygon'))
        left, top, right, bottom = app.map.bbox(marker)
        app._inspect_map_item(SimpleNamespace(x=(left + right) / 2, y=(top + bottom) / 2))
        self.assertEqual(board.selected, 'SIM-02')
        self.assertTrue(board.dialog.visible)

    def test_countdown_raises_a_contact_and_the_board_can_hide(self):
        app, board = self.app, self.board
        board.started -= 4 * 60
        board.tick()
        self.assertEqual(board.by_id['SIM-06']['assessment']['level'], 'critical')
        self.assertEqual(board.tiles['critical-count'].cget('text'), '4')
        self.assertIn('GREY HERON now Critical', app.map_status_label.cget('text'))
        self.assertRegex(board.cards['SIM-06']['eta'].cget('text'), r'^ETA \d\d:\d\d$')
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
