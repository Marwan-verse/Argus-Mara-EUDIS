"""D95: the alert rules on real ships from the team AIS database (no network, synthetic tracks)."""
import unittest

from argus import live_alerts
from argus.detectors import cable_risk
from argus.live_alerts import KEEP_S, LiveTracks, assess

NOW = 1_792_000_000.0  # a fixed UTC moment; tracks below end here


def fixes(mmsi, start, step_s, count, *, lat_step=0.0, lon_step=0.0, sog=2.0, cog=90.0, nav=0, until=NOW):
    lat, lon = start
    rows = []
    for index in range(count):
        t = until-(count-1-index)*step_s
        rows.append([mmsi, t, lat+index*lat_step, lon+index*lon_step, sog, cog, None, nav])
    return rows


def packet(*tracks, static=None, truncated=False):
    rows = sorted((row for track in tracks for row in track), key=lambda row: row[1])
    return {'positions': rows, 'static': static or {}, 'truncated': truncated}


class FakeDatabase:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, payload):
        self.calls.append(payload)
        return self.answers.pop(0)


# The Dublin–Holyhead illustrative route passes (53.36, -5.70); Dublin port is at about (53.345, -6.20).
LOITERER = fixes('250000001', (53.358, -5.705), 60, 120, lon_step=.0002, sog=1.5)  # two hours slow on the line
TRANSIT = fixes('250000002', (53.20, -5.60), 60, 40, lat_step=.006, sog=14.0, cog=0)  # crosses at 14 kn
IN_PORT = fixes('250000003', (53.345, -6.20), 60, 90, sog=1.0)
MOORED = fixes('250000004', (53.40, -5.40), 60, 90, sog=0.0, nav=5)
FAR = fixes('250000005', (52.50, -4.50), 60, 90, sog=1.0)
STATIC = {'250000001': {'name': 'TEST LOITERER', 'ship_type': '70', 'length_m': '150'},
          '250000002': {'name': 'TEST TRANSIT', 'ship_type': '70', 'length_m': '120'}}


class LiveAlertTests(unittest.TestCase):
    def load(self, *tracks):
        live = LiveTracks(rpc=FakeDatabase(packet(*tracks, static=STATIC)))
        live.refresh(NOW)
        return live

    def test_a_ship_loitering_on_a_cable_route_raises_a_real_alert_for_review(self):
        items = assess(self.load(LOITERER, TRANSIT).vessels(NOW), NOW, watchlist=None)
        self.assertEqual([item['mmsi'] for item in items], ['250000001'])
        item = items[0]
        self.assertEqual((item['label'], item['name'], item['vessel_type'], item['length_m']),
                         ('real', 'TEST LOITERER', 'Cargo ship', 150.0))
        self.assertEqual(item['line_id'], 'dublin-holyhead')
        self.assertIn('cable_risk', item['detectors'])
        self.assertNotEqual(item['assessment']['level'], 'none')
        self.assertIn('for review', item['title'].lower())
        self.assertIn('not evidence of intent', item['recommendation'])

    def test_harbour_craft_and_far_ships_are_not_assessed(self):
        live = self.load(IN_PORT, MOORED, FAR)
        self.assertEqual(live.vessels(NOW), [])
        self.assertEqual(live.skipped, {'in_port': 1, 'in_harbour': 0, 'moored': 1})

    def test_the_first_call_loads_three_hours_and_later_calls_only_new_fixes(self):
        newer = fixes('250000001', (53.358, -5.681), 60, 5, sog=1.5, until=NOW+300)
        database = FakeDatabase(packet(LOITERER, static=STATIC), packet(newer))
        live = LiveTracks(rpc=database)
        live.refresh(NOW)
        stats = live.refresh(NOW+300)
        self.assertEqual(database.calls[0]['p_since'], live_alerts.iso(NOW-live_alerts.TRACK_S))
        self.assertEqual(database.calls[1]['p_since'], live_alerts.iso(NOW-live_alerts.OVERLAP_S))
        self.assertEqual(stats['new_fixes'], 5)
        self.assertEqual(live.cursor, NOW+300)
        later = FakeDatabase(packet())
        live.rpc = later
        live.refresh(NOW+KEEP_S+3600)
        self.assertEqual(live.fixes, {})  # everything older than six hours is dropped

    def test_not_available_speed_and_course_are_left_out(self):
        track = fixes('250000001', (53.358, -5.705), 60, 30, sog=1.5)
        track[-1][4], track[-2][5] = 102.3, 360
        live = self.load(track)
        kept = live.vessels(NOW)[0]['track']
        self.assertEqual(len(kept), 28)
        self.assertTrue(all(fix['sog_kn'] is not None and fix['cog_deg'] is not None for fix in kept))

    def test_only_the_named_detectors_run_when_given(self):
        items = assess(self.load(LOITERER).vessels(NOW), NOW, watchlist=None, detectors=[cable_risk.detect])
        self.assertEqual(items[0]['detectors'], ['cable_risk'])

    def test_a_wrong_database_answer_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'argus_recent_tracks'):
            LiveTracks(rpc=FakeDatabase({'rows': []})).refresh(NOW)


if __name__ == '__main__':
    unittest.main()
