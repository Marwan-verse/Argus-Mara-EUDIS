"""Watchlist detector: OpenSanctions lists feed rules C1, C2 and I5, offline, on real public rows.

The fixture holds 38 unchanged rows of the OpenSanctions maritime.csv of 15 Oct
2026 (CC BY-NC 4.0, credit OpenSanctions). Rows marked "made up" below are test
inputs only. No test touches the network: a fake transport serves the files.
"""
from contextlib import redirect_stdout
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from argus import assemble
from argus import watchlist_data as lists
from argus.assemble import assess_vessel, context_from_scenario
from argus.detectors import watchlist
from argus.levels import assess

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures/opensanctions_maritime_sample.csv"
V1, V2 = "20261015150305-hxm", "20261016150305-abc"
DAY1 = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
DAY2 = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


def sample(drop_imos=(), extra_rows=()) -> bytes:
    """The fixture CSV without some IMOs, plus extra rows, in OpenSanctions' quoting."""
    rows = list(csv.DictReader(io.StringIO(FIXTURE.read_text(encoding="utf-8"), newline="")))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=lists.COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        if row["imo"] not in drop_imos:
            writer.writerow(row)
    for row in extra_rows:
        writer.writerow({column: row.get(column, "") for column in lists.COLUMNS})
    return out.getvalue().encode("utf-8")


def fixture_list():
    return lists.parse(FIXTURE.read_bytes(), meta={"date": "2026-10-15", "version": V1})


def real(mmsi=None, name=None, **fields):
    return {"mmsi": mmsi, "name": name, "label": "real", "track": [], **fields}


def found(vessel, watch):
    return watchlist.detect(vessel, {"watchlist": watch})


class FakeOpenSanctions:
    """Serves index.json, versions.json and one maritime.csv per version; records every URL asked for."""

    def __init__(self, versions: dict):
        self.versions, self.calls = dict(versions), []

    def __call__(self, url, limit):
        self.calls.append(url)
        if url == lists.INDEX_URL:
            latest = max(self.versions)
            return json.dumps({"version": latest, "resources": [
                {"name": "maritime.csv", "url": lists.VERSION_URL.format(version=latest)}]}).encode()
        if url == lists.VERSIONS_URL:
            return json.dumps({"items": sorted(self.versions)}).encode()
        for version, raw in self.versions.items():
            if url == lists.VERSION_URL.format(version=version):
                return raw
        raise AssertionError(f"unexpected URL {url}")


class MidTableTests(unittest.TestCase):
    def test_known_country_codes(self):
        self.assertEqual(lists.mid_info("250123456")["iso"], ["ie"])
        self.assertEqual(lists.mid_info("273126520")["country"], "Russia")
        self.assertEqual(lists.mid_info("610000036")["iso"], ["bj"])  # Benin: the tanker Blue's false flag
        self.assertEqual(lists.mid_info("613414602")["iso"], ["cm"])
        for mid in ("636", "637"):
            self.assertEqual(lists.mid_info(mid + "012345")["iso"], ["lr"])
        for mid in [*range(351, 358), *range(370, 375)]:
            self.assertEqual(lists.mid_info(f"{mid}012345")["iso"], ["pa"], mid)
        self.assertIn("im", lists.mid_info("232001000")["iso"])  # Isle of Man ships use UK MIDs
        self.assertEqual(lists.mid_info("236111000")["iso"], ["gi", "gb"])

    def test_table_is_complete(self):
        table = json.loads(lists.MID_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(table["mids"]), 292)
        for mid, entry in table["mids"].items():
            self.assertRegex(mid, r"^[2-7]\d{2}$")
            for code in entry["iso"]:
                self.assertIn(code, table["names"], mid)

    def test_unallocated_and_non_ship_numbers(self):
        self.assertIsNone(lists.mid_info("260255260"))
        self.assertTrue(lists.unallocated_mid("260255260"))
        self.assertIsNone(lists.mid_info("970123456"))  # a beacon, not a ship
        self.assertFalse(lists.unallocated_mid("970123456"))
        self.assertIsNone(lists.mid_info("12345"))
        self.assertEqual(lists.normalise_mmsi(613414602), "613414602")
        self.assertEqual(lists.normalise_imo("IMO9236353"), "9236353")
        self.assertIsNone(lists.normalise_imo("IMO0000000"))


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.watch = fixture_list()

    def test_rows_of_one_ship_are_grouped_by_imo(self):
        blue = self.watch.records["imo:9236353"]  # five rows: Canada, two EU, UK and GUR
        self.assertEqual(blue["tier"], "confirmed")
        self.assertEqual(blue["sanctioned_by"], ["Canada", "EU", "UK"])
        self.assertEqual(list(blue["mmsis"]), ["613414602"])  # only GUR gives the MMSI
        self.assertEqual(len(blue["flag_history"]), 9)
        self.assertEqual(blue["name"], "BLUE")
        self.assertEqual(len(lists.former_names(blue)), 6)

    def test_tiers(self):
        tiers = {key: record["tier"] for key, record in self.watch.records.items()}
        self.assertEqual(tiers["imo:9252371"], "suspected")  # FENOR: GUR shadow fleet only
        self.assertEqual(tiers["imo:9394882"], "noted")  # MAERSK BOGOR: a Tokyo MoU detention
        self.assertEqual(tiers["imo:7524419"], "noted")  # the other YANTAR: GUR, not shadow fleet
        self.assertEqual(tiers["imo:9861251"], "none")  # inspections only
        self.assertNotIn("imo:0011359", self.watch.records)  # an organisation row

    def test_rows_without_imo_join_by_mmsi(self):
        nega = [record for record in self.watch.records.values() if "273337970" in record["mmsis"]]
        self.assertEqual(len(nega), 1)  # GUR and OFAC rows, neither with an IMO
        self.assertEqual(nega[0]["tier"], "confirmed")

    def test_other_files_are_refused(self):
        with self.assertRaises(ValueError):
            lists.parse(b"name,mmsi\nBLUE,613414602\n")


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.watch = fixture_list()

    def test_a_name_never_makes_a_match(self):
        self.assertEqual(found(real("273546520", "YANTAR"), self.watch), [])  # the intelligence ship
        self.assertEqual(found(real("235123456", "BLUE"), self.watch), [])

    def test_the_two_yantars_stay_apart(self):
        tanker = found(real("273127520", "YANTAR"), self.watch)[0]
        self.assertEqual(tanker["related"]["imo"], "9332781")
        self.assertEqual(tanker["related"]["tier"], "confirmed")  # sanctioned as Lang Ya / Aqua Titan
        other = found(real(imo="7524419", name="YANTAR"), self.watch)[0]
        self.assertEqual((other["related"]["tier"], other["obs"]), ("noted", {}))

    def test_an_mmsi_shared_by_two_records_needs_the_name(self):
        unclear = found(real("312429000"), self.watch)[0]
        self.assertEqual((unclear["related"]["kind"], unclear["obs"]), ("ambiguous", {}))
        shared_alias = found(real("312429000", "SMOOTH SEA 22"), self.watch)[0]  # RUSI gives both records this alias
        self.assertEqual(shared_alias["related"]["kind"], "ambiguous")
        picked = found(real("312429000", "SUBBLIC"), self.watch)[0]
        self.assertEqual(picked["related"]["imo"], "8514045")

    def test_imo_and_an_old_inspection_mmsi_find_the_ship(self):
        self.assertEqual(found(real(imo="IMO9236353"), self.watch)[0]["related"]["matched_by"], "IMO")
        serena = found(real("613471602", "SERENA"), self.watch)[0]  # Tokyo MoU recorded this MMSI
        self.assertEqual(serena["related"]["imo"], "9255660")
        self.assertTrue(serena["obs"]["watchlist"])


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.watch = fixture_list()

    def test_sanctioned_tanker_gets_c1_c2_and_i5(self):
        finding = found(real("613414602", "BLUE"), self.watch)[0]
        self.assertEqual(finding["obs"], {"watchlist": True, "flag_risk": True, "identity_changes": 6,
                                          "identity_changes_basis": watchlist.I5_BASIS})
        text = " ".join(finding["reasons"])
        for words in ("Canada, EU, UK", "GUR records 9 flags", "CC BY-NC 4.0", "not proof"):
            self.assertIn(words, text)
        self.assertEqual(finding["strength"], 1.0)

    def test_shadow_fleet_without_sanctions_is_suspected(self):
        finding = found(real("314898000", "FENOR"), self.watch)[0]
        self.assertEqual(finding["related"]["tier"], "suspected")
        self.assertTrue(finding["obs"]["watchlist"])
        self.assertIn("not sanctioned yet", finding["reasons"][0])

    def test_flag_risk_signs(self):
        apama = found(real("256845000", "APAMA"), self.watch)[0]
        self.assertIn("256 belongs to Malta, but the lists give its flag as Iran", apama["reasons"][1])
        ira = found(real("613407300", "IRA"), self.watch)[0]
        self.assertIn("GUR lists its current flag as unknown or false", " ".join(ira["reasons"]))
        blue = self.watch.records["imo:9236353"]
        self.assertTrue(any("looks made up" in sign for sign in lists.flag_signs(blue, "610000036")))
        self.assertFalse(any("looks made up" in sign for sign in lists.flag_signs(blue, "613414602")))

    def test_a_different_ais_name_warns_but_the_mmsi_still_counts(self):
        scout = found(real("273126520", "SCOUT"), self.watch)[0]  # GUR spells it SKAUT
        self.assertTrue(scout["obs"]["watchlist"])
        self.assertIn("not among the listed names", scout["reasons"][1])
        self.assertEqual(scout["strength"], 0.6)

    def test_port_state_records_score_nothing(self):
        finding = found(real("563514000", "MAERSK BOGOR"), self.watch)[0]
        self.assertEqual((finding["related"]["tier"], finding["obs"]), ("noted", {}))
        self.assertIn("Tokyo MoU detentions", finding["reasons"][0])
        self.assertNotIn("inspections", finding["reasons"][0])

    def test_distress_beacons_are_labelled_without_points(self):
        for mmsi, kind in (("970123456", "AIS-SART"), ("972123456", "man-overboard"), ("974123456", "EPIRB")):
            finding = watchlist.detect({"mmsi": mmsi, "label": "simulated"}, {"watchlist": self.watch})[0]
            self.assertEqual((finding["related"]["kind"], finding["obs"]), ("beacon", {}))
            self.assertIn("Possible distress beacon, check", finding["reasons"][0])
            self.assertIn(kind, finding["reasons"][0])

    def test_unallocated_country_code_is_noted(self):
        finding = found(real("260255260"), self.watch)[0]
        self.assertEqual((finding["related"]["kind"], finding["obs"]), ("number", {}))

    def test_fictional_vessels_are_never_compared_with_real_lists(self):
        simulated = {"mmsi": "613414602", "name": "BLUE", "label": "simulated", "track": []}
        self.assertEqual(watchlist.detect(simulated, {"watchlist": self.watch}), [])
        self.assertEqual(watchlist.detect({**simulated, "label": "fictional"}, {"watchlist": self.watch}), [])

    def test_without_a_list_copy_there_are_no_list_findings(self):
        self.assertEqual(found(real("613414602", "BLUE"), None), [])
        with mock.patch.object(lists, "load", return_value=None):
            self.assertEqual(watchlist.detect(real("613414602", "BLUE"), {}), [])


class LevelTests(unittest.TestCase):
    def test_registered_with_the_assembler(self):
        self.assertIn(watchlist.detect, assemble.DETECTORS)

    def test_listed_tanker_passing_calmly_stays_low(self):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        context = {**context_from_scenario(scenario), "watchlist": fixture_list()}
        # West of Ireland, northbound at 12 kn, far from every line: list cues only.
        track = [{"t": minute * 60, "lat": 51.5 + minute * 0.0033, "lon": -11.6, "sog_kn": 12.0, "cog_deg": 0.0}
                 for minute in range(31)]
        vessel = {"mmsi": "613414602", "name": "BLUE", "label": "real", "ship_type": 80, "ais_class": "A",
                  "ais_length_m": 265, "track": track}
        result = assess_vessel(vessel, context)
        self.assertEqual([finding["detector"] for finding in result["findings"]], ["watchlist"])
        self.assertEqual(result["assessment"]["level"], "low")
        self.assertEqual(result["assessment"]["basis"], "B0 I1 P0 A0 C3 = 4")

    def test_i5_text_names_its_basis(self):
        listed = assess({"identity_changes": 6, "identity_changes_basis": watchlist.I5_BASIS})
        text = next(factor["text"] for factor in listed["factors"] if factor["code"] == "I5")
        self.assertIn("6× (former names recorded by the lists; dates not given)", text)
        self.assertNotIn("12 months", text)
        plain = assess({"identity_changes": 1})
        self.assertIn("in 12 months", next(f["text"] for f in plain["factors"] if f["code"] == "I5"))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        lists._cache.clear()

    def tearDown(self):
        lists._cache.clear()
        self.folder.cleanup()

    def test_checks_at_most_once_a_day_and_keeps_a_dated_copy(self):
        source = FakeOpenSanctions({V1: sample()})
        self.assertEqual(lists.update(self.root, now=DAY1, transport=source, min_vessels=1)["action"], "downloaded")
        self.assertTrue((self.root / f"snapshots/maritime-2026-10-15-{V1}.csv.gz").is_file())
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual((state["latest"]["date"], len(state["latest"]["sha256"])), ("2026-10-15", 64))
        self.assertEqual(len(source.calls), 2)
        later = DAY1.replace(hour=20)
        self.assertEqual(lists.update(self.root, now=later, transport=source, min_vessels=1)["action"], "skipped")
        self.assertEqual(len(source.calls), 2)  # no request at all the same day
        self.assertEqual(lists.update(self.root, now=DAY2, transport=source, min_vessels=1)["action"], "unchanged")
        self.assertEqual(source.calls[2:], [lists.INDEX_URL])  # the small index only, no second download

    def test_since_and_until_come_from_the_kept_copies(self):
        lists.update(self.root, now=DAY1, transport=FakeOpenSanctions({V1: sample(drop_imos={"IMO9187631"})}),
                     min_vessels=1)
        second = FakeOpenSanctions({V1: b"", V2: sample(drop_imos={"IMO9252371"})})  # APAMA added, FENOR removed
        self.assertEqual(lists.update(self.root, now=DAY2, transport=second, min_vessels=1)["action"], "downloaded")
        watch = lists.load(self.root)
        blue = found(real("613414602", "BLUE"), watch)[0]
        self.assertIn("On the list since 15 Oct 2026 or earlier (the oldest copy kept here)", blue["reasons"][0])
        apama = found(real("256845000", "APAMA"), watch)[0]
        self.assertIn("On the list since 16 Oct 2026.", apama["reasons"][0])
        fenor = found(real("314898000", "FENOR"), watch)[0]
        self.assertEqual((fenor["related"]["kind"], fenor["obs"]), ("delisted", {}))
        self.assertIn("until 15 Oct 2026", fenor["reasons"][0])

    def test_gur_naming_before_sanctions_is_shown(self):
        lists.update(self.root, now=DAY1, transport=FakeOpenSanctions({V1: sample()}), min_vessels=1)
        made_up = {"type": "VESSEL", "caption": "FENOR", "imo": "IMO9252371", "risk": "sanction",  # made up for the test
                   "datasets": "gb_fcdo_sanctions", "id": "test-sanction", "url": "https://example.org/test"}
        lists.update(self.root, now=DAY2, transport=FakeOpenSanctions({V2: sample(extra_rows=[made_up])}),
                     min_vessels=1)
        fenor = found(real("314898000", "FENOR"), lists.load(self.root))[0]
        self.assertEqual(fenor["related"]["tier"], "confirmed")
        self.assertIn("On the list since 16 Oct 2026; GUR named it from 15 Oct 2026, before the sanctions",
                      fenor["reasons"][0])

    def test_works_offline_from_the_newest_copy(self):
        lists.update(self.root, now=DAY1, transport=FakeOpenSanctions({V1: sample()}), min_vessels=1)
        lists._cache.clear()
        with mock.patch.dict(os.environ, {"ARGUS_WATCHLIST_DIR": str(self.root)}), \
                mock.patch.object(lists, "_http_get", side_effect=AssertionError("network")):
            finding = watchlist.detect(real("613414602", "BLUE"), {})[0]
        self.assertTrue(finding["obs"]["watchlist"])
        self.assertIsNone(lists.load(self.root / "missing"))

    def test_a_broken_or_tiny_download_keeps_the_previous_copy(self):
        lists.update(self.root, now=DAY1, transport=FakeOpenSanctions({V1: sample()}), min_vessels=1)
        with self.assertRaises(ValueError):
            lists.update(self.root, now=DAY2, transport=FakeOpenSanctions({V2: b"name\nBLUE\n"}), min_vessels=1)
        with self.assertRaises(ValueError):  # a real file has about 20,800 vessels
            lists.update(self.root, now=DAY2, transport=FakeOpenSanctions({V2: sample()}))
        self.assertEqual(lists.load(self.root).meta["version"], V1)

    def test_backfill_adds_older_versions_to_the_history(self):
        older = {"20260710150302-bjl": sample(drop_imos={"IMO9236353"}), "20260712150301-kat": sample(),
                 "20260720150301-xyz": sample(), V1: sample()}
        lists.update(self.root, now=DAY1, transport=FakeOpenSanctions({V1: sample()}), min_vessels=1)
        added = lists.backfill(self.root, every_days=7, transport=FakeOpenSanctions(older), min_vessels=1)
        self.assertEqual(added, ["20260710150302-bjl", "20260720150301-xyz"])  # 12 Jul is within a week of 10 Jul
        watch = lists.load(self.root)
        self.assertEqual(watch.oldest_version_date(), "2026-07-10")
        self.assertIn("since 20 Jul 2026.", found(real("613414602", "BLUE"), watch)[0]["reasons"][0])
        self.assertIn("since 10 Jul 2026 or earlier", found(real("314898000", "FENOR"), watch)[0]["reasons"][0])


class ScanTests(unittest.TestCase):
    def test_scan_groups_live_contacts(self):
        contacts = [{"mmsi": "613414602", "name": "BLUE", "lat": 51.5, "lon": -11.6, "received_utc": "2026-10-16T10:00Z"},
                    {"mmsi": "314898000", "name": "FENOR", "lat": 49.1, "lon": -5.7},
                    {"mmsi": "563514000", "name": "MAERSK BOGOR", "lat": 49.5, "lon": -4.8},
                    {"mmsi": "972000001", "name": None, "lat": 53.3, "lon": -6.1},
                    {"mmsi": "250000076", "name": "DOLPHIN DISCOVERY", "lat": 52.1, "lon": -10.3}]
        report = lists.scan_vessels(contacts, fixture_list())
        counts = {group: len(report[group]) for group in ("confirmed", "suspected", "noted", "beacons")}
        self.assertEqual(counts, {"confirmed": 1, "suspected": 1, "noted": 1, "beacons": 1})
        self.assertEqual(report["confirmed"][0]["list_only_level"], "Low: B0 I1 P0 A0 C3 = 4")
        self.assertEqual(report["confirmed"][0]["position"], [51.5, -11.6])

    def test_command_line_check_works_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            lists._cache.clear()
            lists.update(folder, now=DAY1, transport=FakeOpenSanctions({V1: sample()}), min_vessels=1)
            out = io.StringIO()
            with redirect_stdout(out):
                code = lists.main(["--dir", folder, "check", "613414602", "--name", "BLUE"])
            lists._cache.clear()
        self.assertEqual(code, 0)
        self.assertIn("On a sanctions list (Canada, EU, UK): BLUE (IMO 9236353)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
