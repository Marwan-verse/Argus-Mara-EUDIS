"""Editable fictional exercise branches using the existing Brain and fleet engines."""
from copy import deepcopy
import math

from argus.assemble import assess_vessel, context_from_scenario
from argus.countdown import step
from argus.detectors import cable_risk
from argus.prediction import v_max_kn
from argus.responders import assess_fleet, dead_reckoning, load_fleet


class ScenarioLab:
    """A private in-memory branch. Observed fixes never include future truth."""
    def __init__(self, scenario, mmsi, start):
        self.scenario = deepcopy(scenario)
        self.vessel = deepcopy(next(v for v in scenario["vessels"] if str(v["mmsi"]) == str(mmsi)))
        self.vessel["label"] = "fictional"
        self.vessel["track"] = [f for f in self.vessel["track"] if f["t"] <= start]
        if not self.vessel["track"]:
            raise ValueError("Choose a branch time with an observed fix")
        last = self.vessel["track"][-1]
        self.now = self.start = float(last["t"])
        self.truth = [deepcopy(last)]
        self.speed, self.course = last["sog_kn"], last["cog_deg"]
        self.ais = True
        self.wind = 0
        self.actions = []
        self.fleet = load_fleet(t0_utc=scenario.get("t0_utc"))
        # Satellite observations from the original story do not follow a new branch.
        self.scenario["detections"] = []

    def configure(self, speed, course, ais=True, wind=0):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (speed, course, wind)):
            raise ValueError("Speed, course and wind must be finite numbers")
        if not 0 <= speed <= 40 or not 0 <= course < 360 or not 0 <= wind <= 80:
            raise ValueError("Use speed 0–40 kn, course 0–359.9°, and wind 0–80 kn")
        self.speed, self.course, self.ais, self.wind = speed, course, bool(ais), wind
        self.actions.append({"t": self.now, "speed_kn": speed, "course_deg": course, "ais": bool(ais), "wind_kn": wind})

    def advance(self, seconds=60):
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 1800:
            raise ValueError("Advance between 1 and 1800 exercise seconds")
        if self.now + seconds - self.start > 3 * 3600:
            raise ValueError("This branch is limited to three hours; reset to try another plan")
        remaining = seconds
        while remaining:
            span = min(60, remaining)
            lat, lon = step(self.truth[-1]["lat"], self.truth[-1]["lon"], self.course, self.speed * span / 3600)
            if not -85 <= lat <= 85 or not -180 <= lon <= 180:
                raise ValueError("Branch left the supported exercise map")
            self.now += span
            fix = {"t": self.now, "lat": lat, "lon": lon, "sog_kn": self.speed, "cog_deg": self.course}
            self.truth.append(fix)
            if self.ais:
                self.vessel["track"].append(deepcopy(fix))
            remaining -= span
        return self.evaluate()

    def evaluate(self):
        result = assess_vessel(self.vessel, context_from_scenario(self.scenario, self.now))
        last = self.vessel["track"][-1]
        cable = next((c for c in self.scenario["cables"] if c["id"] == result["cable_id"]), None)
        eta, method = (None, None)
        if cable:
            path, _ = cable_risk.reach_section(cable)
            eta, method = cable_risk.eta_to(last, path, self.now, self.vessel["track"])
        dark = self.now - last["t"] > cable_risk.DARK_S
        position = dead_reckoning(last["lat"], last["lon"], last.get("cog_deg"), last.get("sog_kn"), last["t"])
        fleet = assess_fleet(self.fleet, position, self.now, None if eta is None else self.now + eta * 60, self.wind)
        return {"now": self.now, "assessment": result, "earliest_min": eta, "eta_method": method,
                "fleet": fleet, "last_observed": deepcopy(last), "observation_age_s": self.now - last["t"],
                "dark": dark, "reachable_radius_nm": v_max_kn(self.vessel["track"], last["t"]) * (self.now-last["t"]) / 3600,
                "note": "Fictional branch. Fleet meetings use last observed course/speed; a dark vessel's location is uncertain. Human review required."}


def encounter_exercise():
    """Small deterministic pair dataset, independent of the shared demo files."""
    vessels = []
    for index, (name, offset, speed, course) in enumerate((
            ("EXERCISE NORTH", 0, 6, 90), ("EXERCISE SOUTH", .2, 6, 90),
            ("EXERCISE MEET A", 5, .5, 0), ("EXERCISE MEET B", 5.15, .5, 0),
            ("EXERCISE TRANSIT", 12, 16, 180))):
        start = step(53.0, -5.3, 0, offset)
        track = []
        for t in range(0, 3601, 60):
            lat, lon = step(*start, course, speed * t / 3600)
            track.append({"t": t, "lat": lat, "lon": lon, "sog_kn": speed, "cog_deg": course})
        vessels.append({"mmsi": f"LAB-{index+1}", "name": name, "label": "fictional", "track": track})
    return vessels
