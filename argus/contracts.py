"""Small, dependency-free checks for the v1 demo JSON contract."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LABELS = {"real", "reconstructed", "simulated", "fictional", "assumption"}
STATES = {"WATCH", "APPROACHING", "ALERT", "CONTACT", "RESOLVED"}


def _require(obj: dict[str, Any], keys: set[str], where: str) -> None:
    if not isinstance(obj, dict):
        raise ValueError(f"{where}: expected an object")
    missing = keys - obj.keys()
    if missing:
        raise ValueError(f"{where}: missing {', '.join(sorted(missing))}")


def _label(obj: dict[str, Any], where: str) -> None:
    if not isinstance(obj, dict):
        raise ValueError(f"{where}: expected an object")
    if obj.get("label") not in LABELS:
        raise ValueError(f"{where}: label must be one of {', '.join(sorted(LABELS))}")


def _point(lat: Any, lon: Any, where: str) -> None:
    if not isinstance(lat, (int, float)) or isinstance(lat, bool) or not -90 <= lat <= 90:
        raise ValueError(f"{where}: latitude must be within -90..90")
    if not isinstance(lon, (int, float)) or isinstance(lon, bool) or not -180 <= lon <= 180:
        raise ValueError(f"{where}: longitude must be within -180..180")


def _nonnegative(value: Any, where: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{where}: must be a nonnegative number")


def validate_scenario(data: dict[str, Any]) -> None:
    _require(data, {"t0_utc", "replay_speed", "cables", "vessels", "detections", "assets"}, "scenario")
    _label(data, "scenario")
    try:
        start = datetime.fromisoformat(data["t0_utc"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("scenario: t0_utc must be an ISO 8601 UTC timestamp") from error
    if start.tzinfo is None or start.utcoffset() != timezone.utc.utcoffset(start):
        raise ValueError("scenario: t0_utc must use UTC")
    if not isinstance(data["replay_speed"], (int, float)) or isinstance(data["replay_speed"], bool) or data["replay_speed"] <= 0:
        raise ValueError("scenario: replay_speed must be positive")
    for key in ("cables", "vessels", "detections", "assets"):
        if not isinstance(data[key], list):
            raise ValueError(f"scenario: {key} must be an array")
    for i, cable in enumerate(data["cables"]):
        where = f"cables[{i}]"
        _require(cable, {"id", "path", "anchor_reachable", "min_depth_m"}, where)
        _label(cable, where)
        if not isinstance(cable["path"], list) or len(cable["path"]) < 2:
            raise ValueError(f"{where}: path needs at least two [lat, lon] points")
        for j, point in enumerate(cable["path"]):
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError(f"{where}.path[{j}]: expected [lat, lon]")
            _point(*point, f"{where}.path[{j}]")
        if not isinstance(cable["anchor_reachable"], list):
            raise ValueError(f"{where}: anchor_reachable must be an array of [lat, lon] points")
        for j, point in enumerate(cable["anchor_reachable"]):
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError(f"{where}.anchor_reachable[{j}]: expected [lat, lon]")
            _point(*point, f"{where}.anchor_reachable[{j}]")
    for i, vessel in enumerate(data["vessels"]):
        where = f"vessels[{i}]"
        _require(vessel, {"mmsi", "name", "track"}, where)
        _label(vessel, where)
        if not isinstance(vessel["track"], list):
            raise ValueError(f"{where}: track must be an array")
        previous_t = -1
        for j, fix in enumerate(vessel["track"]):
            fix_where = f"{where}.track[{j}]"
            _require(fix, {"t", "lat", "lon", "sog_kn", "cog_deg"}, fix_where)
            _point(fix["lat"], fix["lon"], fix_where)
            _nonnegative(fix["t"], f"{fix_where}.t")
            if fix["t"] <= previous_t:
                raise ValueError(f"{fix_where}: t must increase in seconds from t0")
            previous_t = fix["t"]
    for i, detection in enumerate(data["detections"]):
        where = f"detections[{i}]"
        _require(detection, {"t", "lat", "lon", "source", "scene_id", "matched_mmsi"}, where)
        _label(detection, where)
        _point(detection["lat"], detection["lon"], where)
        _nonnegative(detection["t"], f"{where}.t")
    for i, asset in enumerate(data["assets"]):
        _label(asset, f"assets[{i}]")


def validate_alerts(data: dict[str, Any], scenario: dict[str, Any]) -> None:
    _require(data, {"alerts"}, "alerts file")
    if not isinstance(data["alerts"], list):
        raise ValueError("alerts file: alerts must be an array")
    vessels = {v["mmsi"] for v in scenario["vessels"]}
    cables = {c["id"] for c in scenario["cables"]}
    for i, alert in enumerate(data["alerts"]):
        where = f"alerts[{i}]"
        _require(alert, {"id", "t", "mmsi", "vessel_name", "state", "score", "reasons", "segment_id", "distance_km", "eta_expected_s", "eta_earliest_s", "options", "evidence_url"}, where)
        _nonnegative(alert["t"], f"{where}.t")
        _nonnegative(alert["distance_km"], f"{where}.distance_km")
        if not isinstance(alert["score"], (int, float)) or isinstance(alert["score"], bool) or not 0 <= alert["score"] <= 1:
            raise ValueError(f"{where}: score must be within 0..1")
        if alert["mmsi"] not in vessels or alert["segment_id"] not in cables:
            raise ValueError(f"{where}: references a vessel or cable absent from the scenario")
        if alert["state"] not in STATES:
            raise ValueError(f"{where}: unknown state")
        if not isinstance(alert["reasons"], list) or not all(isinstance(r, str) for r in alert["reasons"]):
            raise ValueError(f"{where}: reasons must be an array of text")
        for key in ("eta_expected_s", "eta_earliest_s"):
            _nonnegative(alert[key], f"{where}.{key}")
        if alert["eta_earliest_s"] > alert["eta_expected_s"]:
            raise ValueError(f"{where}: earliest ETA exceeds expected ETA")
        if not isinstance(alert["options"], list):
            raise ValueError(f"{where}: options must be an array")
        for j, option in enumerate(alert["options"]):
            option_where = f"{where}.options[{j}]"
            _require(option, {"asset", "eta_s", "in_time"}, option_where)
            _label(option, option_where)
            eta = option["eta_s"]
            if eta is not None:
                _nonnegative(eta, f"{option_where}.eta_s")
            if not isinstance(option["in_time"], bool) or option["in_time"] != (eta is not None and eta <= alert["eta_earliest_s"]):
                raise ValueError(f"{option_where}: in_time must match the earliest ETA")


def validate_files(scenario_path: Path, alerts_path: Path) -> tuple[int, int]:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
    validate_scenario(scenario)
    validate_alerts(alerts, scenario)
    return len(scenario["vessels"]), len(alerts["alerts"])
