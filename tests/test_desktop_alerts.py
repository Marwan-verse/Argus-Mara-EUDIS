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
        return list(self.board.order)

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
        self.assertEqual(len(order), 26)  # Medium and above: one incident card each; Low is folded away
        ranks = [RANK[board.by_id[key]['assessment']['level']] for key in order]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        # SIM-06, SIM-44 and SIM-48 are raised one level: no responder reaches them before their line ETA.
        # Stories SIM-50 to SIM-52 are watched at T+90 (SIM-53 starts at T+95).
        # Site contacts SIM-61 and SIM-64 are High, SIM-62 and SIM-63 Medium; SIM-54 is a Low stop (D63).
        self.assertEqual([board.tiles[f'{level}-count'].cget('text') for level in ('critical', 'high', 'medium', 'low')],
                         ['6', '8', '12', '31'])
        self.assertEqual(board.cards['SIM-01']['stripe'].cget('bg'), STYLE['critical'][0])
        self.assertIn('In corridor', board.cards['SIM-01']['eta'].cget('text'))
        self.assertIn('26 new', app.alert_counts_label.cget('text'))
        self.assertEqual(board.summary.cget('text'), '26 open · 0 escalated')
        self.assertEqual(self.flags('SIM-45'), ['AIS spoofing?'])
        self.assertEqual(len(self.map_tags('sim-alert:')), len(board.items) - 2)  # SIM-53 starts at T+95, SIM-55 at T+140
        badge = next(item for item in app.map.find_withtag('sim-badge') if app.map.type(item) == 'text')
        self.assertIn('SIMULATED', app.map.itemcget(badge, 'text'))
        board.set_filter('critical')
        self.assertEqual(len(self.packed_cards()), 6)
        self.assertEqual(len(self.map_tags('sim-alert:')), 6)
        board.set_filter('critical')
        self.assertIsNone(board.level_filter)
        board.set_filter('low')
        self.assertIn('SIM-40', self.packed_cards())
        self.assertEqual(len(self.packed_cards()), 31)  # with stories SIM-50 to SIM-52 and the stop SIM-54
        self.assertEqual(self.flags('SIM-40'), ['Small craft · capped Low'])
        board.set_filter(None)
        board.toggle_watching()
        self.assertEqual(len(self.packed_cards()), len(board.items) - 2)  # SIM-53 and SIM-55 are not raised until T+95 and T+140
        board.sort_mode.set('Time to asset')
        board.relayout(top=True)
        self.assertEqual(len(self.packed_cards()), len(board.items) - 2)

    def test_hide_demo_alerts_clears_queue_counts_and_markers_but_keeps_reports(self):
        import json
        import tempfile
        from pathlib import Path
        from argus.vessel_reports import make_report
        board = self.board
        original_cards = self.packed_cards()
        board.open('SIM-01')
        self.app.vessel_reports.add(make_report(
            {'id': '123456789', 'name': 'Reported contact', 'label': 'real', 'lat': 53.2, 'lon': -6.1},
            'Other', 'An analyst observation for review.'), 'analyst')
        board.refresh_reports()
        with tempfile.TemporaryDirectory() as directory:
            self.app.tools.settings_path = Path(directory) / 'preferences.json'
            board.demo_switch.toggle()
            self.root.update()
            self.assertEqual(self.packed_cards(), [])
            self.assertEqual(board.visible_items(), [])
            self.assertEqual(self.map_tags('sim-alert:'), set())
            self.assertTrue(all(value == 0 for value in board.counts().values()))
            self.assertFalse(board.dialog.visible)
            self.assertIsNone(board.selected)
            self.assertTrue(board.reports_frame.winfo_manager())
            self.assertIn('Fictional / simulated alerts hidden', self.app.alert_counts_label.cget('text'))
            self.app.tools.save()
            self.assertIs(json.loads(self.app.tools.settings_path.read_text())['show_demo_alerts'], False)
            board.demo_switch.toggle()
            self.root.update()
            self.assertEqual(self.packed_cards(), original_cards)
            self.assertTrue(self.map_tags('sim-alert:'))
            self.app.tools.settings_path = None

    def test_one_queue_by_importance_real_leads_first_low_folded_away(self):
        """D94: real leads join the severity bands ahead of simulated contacts; Low folds away (remembered)."""
        from desktop_alerts import CardRow, HeaderRow, LeadRow
        board = self.board

        def lead(name, priority, day, **extra):
            return {'id': name, 'name': name, 'mmsi': '123456789', 'title': f'{name} title', 'kind': 'image_without_ais',
                    'acquired_utc': f'2026-10-{day:02d}T12:00:00Z', 'source_label': 'real', 'reason': 'Synthetic.',
                    'scene_id': 'a' * 24, 'priority': priority, 'priority_reason': f'{priority} because', **extra}
        leads = [lead('LOW-A', 'low', 10), lead('HIGH-A', 'high', 11), lead('MED-OLD', 'medium', 9),
                 lead('UNKNOWN-NEW', None, 14), lead('LOW-B', 'low', 12),
                 lead('LOW-CHANGED', 'low', 8, evidence_changed=True), lead('HIGH-KEYED', 'high', 13, evidence_key='k')]
        board.refresh_evidence({'leads': leads, 'reviews_checked': 7, 'reviews_pending': 0})
        self.root.update()

        def queue():
            found = []
            for row in board.list.rows:
                if isinstance(row, HeaderRow):
                    found.append(row.key)
                elif isinstance(row, LeadRow):
                    found.append(row.lead.title.split(' · ')[0])
                elif isinstance(row, CardRow):
                    found.append('card')
            return found

        rows = queue()
        high = rows.index('header:high')
        # High: real leads first (newest first), then the simulated incident cards.
        self.assertEqual(rows[high + 1:high + 3], ['HIGH-KEYED', 'HIGH-A'])
        self.assertEqual(rows[high + 3], 'card')
        medium = rows.index('header:medium')
        self.assertEqual(rows[medium + 1:medium + 3], ['UNKNOWN-NEW', 'MED-OLD'])  # Unknown priority is shown
        self.assertNotIn('LOW-A', rows)  # Low folds away by default
        self.assertIn('header:low', rows)
        self.assertEqual([board.tiles[f'{level}-count'].cget('text') for level in ('critical', 'high', 'medium', 'low')],
                         ['6', '10', '14', '34'])
        keyed = next(row.lead for row in board.list.rows if isinstance(row, LeadRow) and row.lead.title.startswith('HIGH-KEYED'))
        self.assertEqual(keyed.secondary.text, 'Record analyst outcome')
        self.assertEqual(keyed.tag, 'SAT · REAL')
        board.toggle_low()
        rows = queue()
        low = rows.index('header:low')
        self.assertEqual(rows[low + 1:low + 4], ['LOW-CHANGED', 'LOW-B', 'LOW-A'])  # Changed evidence first, then newest
        self.assertIs(self.app.tools.settings['show_low_alerts'], True)
        board.toggle_low()
        self.assertNotIn('LOW-A', queue())
        self.assertIs(self.app.tools.settings['show_low_alerts'], False)

    def test_satellite_leads_remain_visible_with_demo_hidden_and_page_all_results(self):
        board = self.board
        board.show_demo_alerts.set(False)
        board.toggle_demo_alerts()
        leads = [{'id': str(i), 'name': 'TEST CONTACT', 'mmsi': '123456789',
                  'title': 'AIS vessel not detected in clear-water image',
                  'acquired_utc': '2026-10-13T12:00:00Z', 'source_label': 'real',
                  'reason': 'Synthetic test of presentation only.', 'scene_id': 'a'*24}
                 for i in range(51)]
        board.refresh_evidence({'leads': leads, 'reviews_checked': 3, 'reviews_pending': 1})
        self.root.update()
        self.assertTrue(board.evidence_frame.winfo_manager())
        self.assertEqual(self.packed_cards(), [])
        self.assertIn('51 satellite / AIS leads', self.app.alert_counts_label.cget('text'))
        entries = [link for link in board.evidence_frame.links if link.kind == 'entry']
        self.assertEqual(len(entries), 50)
        next_link = next(link for link in board.evidence_frame.links if link.text == 'Next')
        next_link.invoke()
        self.assertEqual(board.evidence_page, 1)
        self.assertEqual(len([link for link in board.evidence_frame.links if link.kind == 'entry']), 1)
        self.assertTrue(all(v == 0 for v in board.counts().values()))

    def test_satellite_analyst_outcome_is_saved_and_can_be_shown_again(self):
        import tempfile
        import time
        from pathlib import Path
        from desktop_evidence_review import EvidenceReview
        from test_satellite_disposition import lead_fixture
        with tempfile.TemporaryDirectory() as temp:
            workspace, _ = lead_fixture(Path(temp)/'satellite')
            self.app.satellite.workspace = workspace
            result = workspace.comparison_index()
            self.board.refresh_evidence(result)
            form = EvidenceReview(self.board, result['leads'][0])
            form.outcome.set('Reviewed — no concern identified')
            form.reason.insert('1.0', 'Synthetic test analyst disposition.')
            form.save()
            deadline = time.monotonic()+5
            while form.window.winfo_exists() and time.monotonic()<deadline:
                self.root.update()
                time.sleep(.02)
            self.assertFalse(form.window.winfo_exists())
            self.assertEqual(self.board.evidence_leads[0]['review_status'], 'reviewed_no_concern')
            self.assertFalse(any('Open image evidence' in link.text for link in self.board.evidence_frame.links))
            self.board.show_reviewed_evidence.set(True)
            self.board.paint_evidence()
            self.assertTrue(any('Reviewed — no concern identified' in link.text
                                for link in self.board.evidence_frame.links))
            self.assertEqual(self.errors, [])

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
        # The card shortens long text with an ellipsis to fit; fonts differ between macOS and Windows.
        shown = board.cards['SIM-01']['status'].cget('text')
        self.assertTrue(shown.startswith('Escalated · Irish'), shown)
        full_status = f"Escalated · Irish Coast Guard (MRCC) · hand-written · {board.by_id['SIM-01']['line_name']}"
        self.assertTrue(full_status.startswith(shown.removesuffix('…')), shown)
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
        # A country-wide view on a small runner display can overlap callouts.
        # Inspect the actual marker after centering/zooming to this contact.
        contact = board.by_id['SIM-02']
        app._change_map_center((contact['lat'], contact['lon']))
        app._zoom_by(3)
        app.motion.finish_zoom()  # Mid-glide the chart is one moving picture; markers return when it lands
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
            return dialog.body.texts()

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
        dialog.body.canvas.yview_moveto(1)
        board.open('SIM-44')
        self.assertEqual(dialog.body.canvas.yview()[0], 0)
        self.assertTrue(any(text.startswith('Also named: Gas interconnector IC2') for text in texts()))

    def test_who_can_reach_it_shows_on_card_window_and_map_and_a_storm_grounds_drones(self):
        board, dialog = self.board, self.board.dialog

        def texts():
            return dialog.body.texts()

        card = board.cards['SIM-41']['respond']
        self.assertTrue(card.winfo_manager())
        self.assertEqual(card.cget('text'), 'Drone D1 · 42 min · in time (+3 min)')
        self.assertTrue(board.cards['SIM-06']['respond'].cget('text').startswith('No responder in time'))
        self.assertFalse(board.cards['SIM-40']['respond'].winfo_manager())  # watched, not an incident
        board.open('SIM-41')
        self.assertNotIn('WHO CAN REACH IT', texts())  # shown while escalating, not in the plain review
        dialog.open_form('escalate')
        shown = texts()
        self.assertIn('WHO CAN REACH IT', shown)
        self.assertNotIn('WHY THIS LEVEL', shown)
        self.assertIn('Drone D1 · 42 min · in time (+3 min)', shown)
        self.assertIn('42 min · in time (+3)', shown)
        self.assertTrue(any(text.startswith('out of range (87 nm from base') for text in shown))
        self.assertTrue(self.map_tags('sim-response'))
        board.toggle_storm()
        self.assertTrue(board.replay.storm)
        self.assertEqual(board.by_id['SIM-41']['assessment']['level'], 'critical')
        self.assertTrue(card.cget('text').startswith('No responder in time'))
        self.assertIn('wind 30 kn above the 25 kn drone limit', texts())
        self.assertIn('Exercise wind 30 kn', self.app.map_status_label.cget('text'))
        board.toggle_storm()
        self.assertEqual(board.by_id['SIM-41']['assessment']['level'], 'high')
        dialog.cancel_form()
        self.assertIn('WHY THIS LEVEL', texts())
        board.deselect()
        self.assertFalse(self.map_tags('sim-response'))

    def test_send_needs_response_review_and_shows_the_conflict_on_the_other_card(self):
        board = self.board
        board.open('A1')
        with patch.object(self.app, 'require_tool', return_value=False) as check:
            board.send('A1', 'D1')
        check.assert_called_once_with('response.review')
        self.assertEqual(board.replay.assignments, {})
        board.send('A1', 'D1')
        self.assertEqual(board.cards['A1']['respond'].cget('text'), 'Sent: Drone D1 · 31 min · in time (+30 min)')
        self.assertTrue(board.cards['SIM-41']['respond'].cget('text').startswith(
            'No responder in time · D1 assigned to INC-'))  # the narrow card may clip the number
        self.assertEqual(board.by_id['SIM-41']['assessment']['level'], 'critical')
        self.assertIn('SEA LARK now Critical: no responder in time', self.app.map_status_label.cget('text'))
        self.assertIn('Sent Drone D1', board.history['A1'][-1][1])
        board.recall('A1', 'D1')
        self.assertEqual(board.by_id['SIM-41']['assessment']['level'], 'high')
        self.assertEqual(board.cards['SIM-41']['respond'].cget('text'), 'Drone D1 · 42 min · in time (+3 min)')

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
