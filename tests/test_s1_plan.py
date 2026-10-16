"""Next Sentinel-1 look from ESA acquisition plans: parsing, the swath polygon test, the cache and the responder row."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from argus import responders, s1_plan
from argus.satellite import IRISH_BBOX

NEWER = "s1d_mp_user_20261020t060000_20261030t000000"
OLDER = "s1d_mp_user_20261019t060000_20261029t000000"
DUBLIN_BAY = (53.3, -6.0)
# Ascending strip across the Irish Sea whose four vertices all lie outside Irish waters
# (44-63 N): a vertex test misses it, the polygon test must not.
LONG_RING = "-3.0,44.0,0 -6.5,44.4,0 -8.5,63.0,0 -4.5,63.2,0 -3.0,44.0,0"
# Descending strip far west in the Atlantic: no coastal cell, but it covers 53 N 15.9 W.
WEST_RING = "-14.5,56.0,0 -14.8,50.0,0 -17.3,50.0,0 -17.0,56.0,0 -14.5,56.0,0"
ARCTIC_RING = "10,76,0 20,76,0 22,80,0 8,80,0 10,76,0"


def placemark(start, stop, ring, mode="IW", datatake="A1B2", polarisation="DV"):
    return f"""<Placemark><name>{start}</name>
      <TimeSpan><begin>{start}</begin><end>{stop}</end></TimeSpan><styleUrl>{mode}</styleUrl>
      <ExtendedData>
        <Data name="SatelliteId"><value>S1D</value></Data><Data name="DatatakeId"><value>{datatake}</value></Data>
        <Data name="Mode"><value>{mode}</value></Data><Data name="Swath"><value>NA</value></Data>
        <Data name="Polarisation"><value>{polarisation}</value></Data>
        <Data name="ObservationTimeStart"><value>{start}</value></Data>
        <Data name="ObservationTimeStop"><value>{stop}</value></Data>
        <Data name="ObservationDuration"><value>0</value></Data>
        <Data name="OrbitAbsolute"><value>5044</value></Data><Data name="OrbitRelative"><value>103</value></Data>
      </ExtendedData>
      <LinearRing><tessellate>true</tessellate><altitudeMode>clampToGround</altitudeMode>
        <coordinates>{ring}</coordinates></LinearRing></Placemark>"""


def kml(*placemarks):
    """The layout of ESA's files: Document / day Folder / satellite Folder / Placemark, LinearRing directly inside."""
    return ("""<?xml version="1.0" encoding="iso-8859-1"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Planned from fixture</name>
  <Folder><name>2026-10-21</name><Folder><name>S1D</name>""" + "".join(placemarks)
            + "</Folder></Folder></Document></kml>").encode("iso-8859-1")


NEWER_KML = kml(placemark("2026-10-21T18:00:00", "2026-10-21T18:05:00", LONG_RING, datatake="988E"),
                placemark("2026-10-22T07:00:00", "2026-10-22T07:01:30", WEST_RING, datatake="98A0"),
                placemark("2026-10-21T10:00:00", "2026-10-21T10:05:00", ARCTIC_RING, mode="EW", polarisation="DH"),
                placemark("2026-10-23T10:00:00", "2026-10-23T09:00:00", LONG_RING))  # stop before start
OLDER_KML = kml(placemark("2026-10-19T18:10:00", "2026-10-19T18:15:00", LONG_RING, datatake="9801"),
                placemark("2026-10-21T17:59:00", "2026-10-21T18:04:00", LONG_RING, datatake="9880"))
PAGE = ("<ul><li><a href=\"/documents/d/sentinel/%s\">20 - 30 October 2026</a></li>"
        "<li><a href=\"https://documents/d/sentinel/%s\">19 - 29 October 2026</a></li>"
        "<li><a href=\"/documents/d/sentinel/s1d_mp_user_20261010t060000_20261020t000000\">old</a></li>"
        "<li><a href=\"/documents/d/sentinel/s1a_mp_user_20260601t060000_20260621t000000\">retired</a></li></ul>"
        % (NEWER, OLDER))


def fake_esa(log):
    files = {s1_plan.PAGE: PAGE.encode(), s1_plan.DOCUMENTS + NEWER: NEWER_KML, s1_plan.DOCUMENTS + OLDER: OLDER_KML}

    def transport(url, limit):
        log.append(url)
        return files[url]
    return transport


class ParseTests(unittest.TestCase):
    def test_reads_esa_layout_and_counts_unreadable_placemarks(self):
        takes, unreadable = s1_plan.parse_kml(NEWER_KML)
        self.assertEqual((len(takes), unreadable), (3, 1))
        first = takes[0]
        self.assertEqual((first["satellite"], first["mode"], first["polarisation"], first["datatake"]),
                         ("S1D", "IW", "DV", "988E"))
        self.assertEqual((first["start_utc"], first["stop_utc"]), ("2026-10-21T18:00:00Z", "2026-10-21T18:05:00Z"))
        self.assertEqual((first["orbit_absolute"], first["orbit_relative"]), (5044, 103))
        self.assertEqual(first["ring"][0], [-3.0, 44.0])
        self.assertEqual(len(first["ring"]), 4)  # the closing vertex is dropped

    def test_refuses_document_type_declarations_and_bad_names(self):
        with self.assertRaises(ValueError):
            s1_plan.parse_kml(b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY a "aaaa">]><kml>&a;</kml>')
        with self.assertRaises(ValueError):
            s1_plan.plan_record(NEWER_KML, "plan.kml", "2026-10-20T00:00:00Z")

    def test_lists_every_link_form_and_takes_the_newest_plus_the_one_in_force(self):
        listed = s1_plan.listed_plans(PAGE)
        self.assertEqual(len(listed), 4)
        chosen = s1_plan.wanted(listed, s1_plan.epoch("2026-10-19T12:00:00Z"))
        self.assertEqual([plan["file"] for plan in chosen], [NEWER, OLDER])  # S1A retired: nothing
        chosen = s1_plan.wanted(listed, s1_plan.epoch("2026-10-20T12:00:00Z"))
        self.assertEqual([plan["file"] for plan in chosen], [NEWER])


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.plans = [s1_plan.plan_record(OLDER_KML, OLDER, "2026-10-19T00:00:00Z"),
                      s1_plan.plan_record(NEWER_KML, NEWER, "2026-10-20T00:00:00Z")]
        self.long = next(take for take in s1_plan.governing(self.plans) if take["datatake"] == "988E")

    def test_a_long_swath_crossing_the_coast_counts_without_any_vertex_there(self):
        w, s, e, n = IRISH_BBOX
        self.assertFalse(any(w <= lon <= e and s <= lat <= n for lon, lat in self.long["ring"]))
        found = s1_plan.coast_pass(self.long)
        self.assertIsNotNone(found)
        self.assertGreater(found["coasts"].get("East", 0), 50)
        self.assertNotIn("West", found["coasts"])
        self.assertEqual(found["frames_online_utc"],
                         s1_plan.iso(s1_plan.epoch(found["over_coast_to_utc"]) + 3600))

    def test_only_swaths_over_irish_waters_are_kept(self):
        files = {take["datatake"] for plan in self.plans for take in plan["datatakes"]}
        self.assertEqual(files, {"988E", "98A0", "9801", "9880"})  # the Arctic EW strip is dropped
        west = next(take for take in s1_plan.governing(self.plans) if take["datatake"] == "98A0")
        self.assertIsNone(s1_plan.coast_pass(west))

    def test_the_newer_plan_governs_from_its_start(self):
        kept = [(take["datatake"], take["plan_file"]) for take in s1_plan.governing(self.plans)]
        self.assertIn(("9801", OLDER), kept)      # 19 Oct: before the newer plan starts
        self.assertNotIn(("9880", OLDER), kept)   # 21 Oct: replaced by the newer plan's 988E
        self.assertIn(("988E", NEWER), kept)

    def test_time_over_a_position_follows_the_strip(self):
        look = s1_plan.next_look(DUBLIN_BAY, s1_plan.epoch("2026-10-21T12:00:00Z"), self.plans)
        self.assertEqual((look["satellite"], look["swath"]), ("S1D", "inside"))
        # Dublin Bay lies about half-way between the 44.2 N start and the 63.1 N end of the 300 s strip.
        offset = look["time"] - s1_plan.epoch("2026-10-21T18:00:00Z")
        self.assertTrue(130 < offset < 160, offset)
        self.assertEqual(look["frames_online_utc"], s1_plan.iso(look["time"] + 3600))
        west = s1_plan.next_look((53.0, -15.9), s1_plan.epoch("2026-10-21T12:00:00Z"), self.plans)
        self.assertEqual((west["datatake"], west["swath"]), ("98A0", "inside"))

    def test_a_position_near_the_edge_is_flagged_and_one_beyond_it_is_missed(self):
        prepared = s1_plan._prepared(s1_plan._ring(self.long))
        lat, lon = DUBLIN_BAY
        while s1_plan.inside(prepared["poly"], *s1_plan.project(lon, lat)):
            lon += 0.01  # walk east from Dublin Bay until just outside the eastern edge
        self.assertTrue(-5.0 < lon < -3.0, lon)
        edge = s1_plan.look_at(self.long, lat, lon + 10 / (111.32 * math.cos(math.radians(lat))))
        self.assertEqual(edge["swath"], "edge")
        self.assertFalse(edge["inside_plan_footprint"])
        self.assertIsNone(s1_plan.look_at(self.long, lat, lon + 40 / (111.32 * math.cos(math.radians(lat)))))

    def test_a_moving_vessel_is_checked_where_it_is_when_the_satellite_passes(self):
        after = s1_plan.epoch("2026-10-21T12:00:00Z")
        # In the strip at noon, 300 km west of it by the pass: the strip at 18:00 misses it.
        moving = lambda moment: DUBLIN_BAY if moment < after + 3600 else (53.3, -11.0)
        look = s1_plan.next_look(moving, after, self.plans)
        self.assertNotEqual(look and look["datatake"], "988E")

    def test_summary_gives_the_countdown_and_the_frames_delay(self):
        lines = s1_plan.summary(s1_plan.epoch("2026-10-21T12:00:00Z"), 7, self.plans)
        text = "\n".join(lines)
        self.assertIn("Next Sentinel-1 look at the coast in 6 h 0", text)
        self.assertIn("Frames usually online about 1 h after a pass", text)
        self.assertIn("S1D IW DV", text)
        self.assertIn("No planned look at the coast", "\n".join(
            s1_plan.summary(s1_plan.epoch("2026-10-29T12:00:00Z"), 7, self.plans)))


class CacheTests(unittest.TestCase):
    def test_refresh_caches_plans_and_everything_then_works_offline(self):
        log = []
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "s1_plan"
            result = s1_plan.refresh(cache, fake_esa(log), now=s1_plan.epoch("2026-10-19T12:00:00Z"))
            self.assertEqual(result["fetched"], [NEWER, OLDER])
            self.assertEqual(sorted(path.name for path in cache.iterdir()),
                             sorted([NEWER + ".json", NEWER + ".kml", OLDER + ".json", OLDER + ".kml"]))
            record = json.loads((cache / (NEWER + ".json")).read_text(encoding="utf-8"))
            self.assertEqual((record["label"], record["unreadable_placemarks"], record["datatakes_in_file"]),
                             ("real", 1, 3))
            again = s1_plan.refresh(cache, fake_esa(log), now=s1_plan.epoch("2026-10-19T12:00:00Z"))
            self.assertEqual((again["fetched"], len(log)), ([], 4))  # cached files are not fetched again
            plans = s1_plan.load_plans(cache, snapshot=False)  # offline from here on
            self.assertEqual({plan["file"] for plan in plans}, {NEWER, OLDER})
            look = s1_plan.next_look(DUBLIN_BAY, s1_plan.epoch("2026-10-19T12:00:00Z"), plans)
            self.assertEqual((look["datatake"], look["plan_file"]), ("9801", OLDER))

    def test_only_esa_over_https_is_contacted(self):
        for url in ("http://sentinels.copernicus.eu/x", "https://example.com/x"):
            with self.assertRaises(ValueError):
                s1_plan.http_get(url, 10)

    def test_a_damaged_cache_never_breaks_the_window_text(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / (NEWER + ".json")).write_text("{not json", encoding="utf-8")
            with mock.patch.object(s1_plan, "CACHE", Path(temp)), mock.patch.object(s1_plan, "SNAPSHOT", Path(temp) / "none"):
                text = s1_plan.window_text(s1_plan.epoch("2026-10-21T12:00:00Z"))
        self.assertIn("No plan loaded", text)

    def test_old_plans_are_pruned_per_satellite(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            for day in range(10, 16):
                name = "s1d_mp_user_202610%02dt060000_202610%02dt000000" % (day, day + 10)
                (cache / (name + ".json")).write_text("{}", encoding="utf-8")
            removed = s1_plan.prune(cache, keep=4)
            self.assertEqual(len(removed), 2)
            self.assertEqual(len(list(cache.glob("*.json"))), 4)


class ResponderTests(unittest.TestCase):
    """The SAT row of the fleet reads the plan on the replay clock (scenario t0_utc)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        cache = Path(self.temp.name)
        s1_plan.store(OLDER_KML, OLDER, cache, "2026-10-19T00:00:00Z")
        s1_plan.store(NEWER_KML, NEWER, cache, "2026-10-20T00:00:00Z")
        self.patches = [mock.patch.object(s1_plan, "CACHE", cache),
                        mock.patch.object(s1_plan, "SNAPSHOT", cache / "no-snapshot.json")]
        for patch in self.patches:
            patch.start()
        self.sat = {"id": "SAT", "name": "Next Sentinel-1 look", "kind": "satellite", "counts": False,
                    "plan": "esa_s1", "label": "real", "t0_utc": "2026-10-21T12:00:00Z"}

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def test_the_satellite_row_is_the_next_planned_look_at_the_vessel(self):
        position = responders.dead_reckoning(*DUBLIN_BAY, 0, 0, 0)
        row = responders.assess_asset(self.sat, position, 600)
        self.assertEqual(row["status"], "eyes_on")
        self.assertTrue(6 * 3600 - 600 + 130 < row["eta_s"] < 6 * 3600 - 600 + 160, row["eta_s"])
        self.assertTrue(row["name"].startswith("Sentinel-1D pass 18:02 UTC · frames ~19:02"), row["name"])
        self.assertEqual((row["label"], row["look"]["plan_file"], row["counts"]), ("real", NEWER, False))
        self.assertIn("eyes on in 5 h 52 min", responders.row_text(row))
        late = responders.assess_asset(self.sat, position, 600, deadline_s=3600)
        self.assertEqual((late["status"], late["in_time"]), ("late", False))

    def test_without_a_clock_or_a_plan_the_row_says_why(self):
        position = responders.dead_reckoning(*DUBLIN_BAY, 0, 0, 0)
        row = responders.assess_asset({**self.sat, "t0_utc": None}, position, 0)
        self.assertEqual((row["status"], row["reason"]), ("unavailable", "no replay clock for the Sentinel-1 plan"))
        row = responders.assess_asset({**self.sat, "t0_utc": "2026-11-02T00:00:00Z"}, position, 0)
        self.assertIn("plan ends", row["reason"])

    def test_load_fleet_hands_the_replay_clock_to_the_planned_satellite(self):
        fleet = responders.load_fleet(t0_utc="2026-10-16T08:00:00Z")
        sat = next(asset for asset in fleet["assets"] if asset["kind"] == "satellite")
        self.assertEqual((sat["plan"], sat["t0_utc"], sat["label"]), ("esa_s1", "2026-10-16T08:00:00Z", "real"))
        self.assertNotIn("pass_times_s", sat)  # the invented 20400 s pass is gone


class BundledPlanTests(unittest.TestCase):
    """The committed snapshot of ESA's real plans of 15-16 Oct 2026, checked against published frames."""

    def setUp(self):
        self.plans = s1_plan.load_plans(cache=False)
        files = {plan["file"] for plan in self.plans}
        if "s1c_mp_user_20261015t180204_20261106t201100" not in files:
            self.skipTest("snapshot rebuilt without the 15 Oct plans")

    def test_plan_times_match_the_published_frames(self):
        # S1C_IW_GRDH_1SDV_20261015T181352_20261015T181417 covers Dublin Bay (52.02-53.92 N on that edge).
        look = s1_plan.next_look(DUBLIN_BAY, s1_plan.epoch("2026-10-15T18:00:00Z"), self.plans)
        self.assertEqual(look["satellite"], "S1C")
        self.assertTrue(s1_plan.epoch("2026-10-15T18:13:52Z") <= look["time"] <= s1_plan.epoch("2026-10-15T18:14:17Z"))
        # S1D_IW_GRDH_1SDV_20261016T065511_20261016T065536, centre 52.80 N 10.32 W.
        look = s1_plan.next_look((52.80, -10.32), s1_plan.epoch("2026-10-16T06:00:00Z"), self.plans)
        self.assertEqual(look["satellite"], "S1D")
        self.assertTrue(s1_plan.epoch("2026-10-16T06:55:11Z") <= look["time"] <= s1_plan.epoch("2026-10-16T06:55:36Z"))

    def test_next_look_at_the_coast_after_the_snapshot_was_taken(self):
        first = s1_plan.upcoming(s1_plan.epoch("2026-10-16T12:30:00Z"), 7, self.plans)[0]
        self.assertEqual((first["satellite"], first["mode"], s1_plan.span(first)), ("S1D", "IW", "18:05-18:06"))
        self.assertEqual(first["label"], "real")


if __name__ == "__main__":
    unittest.main()
