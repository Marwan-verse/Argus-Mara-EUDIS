"""Source-preserving investigation events and conservative pairwise review leads.

Times are UTC epoch seconds at this boundary. Pair thresholds are assumptions;
neither proximity nor parallel travel establishes coordination or intent.
"""
from bisect import bisect_right
from copy import deepcopy
from datetime import datetime, timezone
import math

LABELS = {"real", "reconstructed", "fictional", "simulated", "assumption"}
PAIR_WINDOW_S = 6 * 3600
MAX_SKEW_S = 60
MAX_GAP_S = 180


def epoch(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.utcoffset() is None:
            raise ValueError("An evidence time must include its UTC offset")
        return value.timestamp()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid evidence time")
    return float(value)


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def distance_nm(a, b):
    """Great-circle distance, including across the date line."""
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlon = lat2 - lat1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 3440.065 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def valid_track(vessel, now=math.inf):
    """Reject malformed/ambiguous time series instead of silently repairing them."""
    if vessel.get("label") not in LABELS:
        raise ValueError("Track requires explicit provenance")
    result = []
    for row in vessel.get("track", []):
        stamp = epoch(row["t"])
        if stamp > now:
            continue
        for key, bound in (("lat", 90), ("lon", 180)):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > bound:
                raise ValueError(f"Invalid {key} in {vessel.get('mmsi')}")
        if result and stamp <= result[-1]["t"]:
            raise ValueError("Track timestamps must be strictly increasing")
        result.append({**deepcopy(row), "t": stamp})
    return result


def timeline(vessel, *, observations=(), reports=(), identity_history=(), now=None):
    """Return immutable-view events, retaining original source records for inspection.

    Satellite candidates are explicitly provisional; unrelated detections are
    available in the separate unassociated-observations view, never assigned here.
    """
    events = []
    identity, label = str(vessel["mmsi"]), vessel.get("label", "assumption")
    end = math.inf if now is None else epoch(now)

    def add(stamp, kind, title, record, position=None, provenance=label, source="Received AIS"):
        if stamp <= end:
            events.append({"t": stamp, "kind": kind, "title": title, "label": provenance,
                           "position": position, "source": source, "record": deepcopy(record)})

    track = valid_track(vessel, end)
    previous = None
    for fix in track:
        if previous:
            delta = fix["t"] - previous["t"]
            if fix.get("stream_id") != previous.get("stream_id") or fix.get("label", label) != previous.get("label", label):
                add(fix["t"], "boundary", "Reception stream or provenance changed", fix)
            elif delta > 900:
                add(fix["t"], "gap", f"AIS reception gap: {delta / 60:.1f} min; cause unknown",
                    {"before": previous, "after": fix}, [fix["lat"], fix["lon"]])
        add(fix["t"], "fix", "Received AIS position", fix, [fix["lat"], fix["lon"]], fix.get("label", label))
        previous = fix
    for record in identity_history:
        if str(record.get("mmsi")) == identity and record.get("label") == label:
            add(epoch(record["observed_utc"]), "identity", "Observed identity declaration change", record,
                source="Local identity observations; observation time, not effective date")
    for record in observations:
        if record.get("label") not in LABELS:
            continue
        # Never merge exercise observations into a real vessel's timeline.
        origin_label = record.get("scene_label", record["label"])
        if (label in {"real", "reconstructed"}) != (origin_label in {"real", "reconstructed"}):
            continue
        candidates = {str(c.get("mmsi")) for c in record.get("candidates", [])}
        if identity != str(record.get("matched_mmsi")) and identity not in candidates:
            continue
        add(epoch(record["acquired_utc"]), "satellite", "Satellite observation; candidate identity only", record,
            [record["lat"], record["lon"]], record["label"], record.get("source", "Satellite evidence"))
    for entry in reports:
        report = entry["report"]
        subject = report["vessel"]
        if str(subject["id"]) == identity and subject["label"] == label:
            add(epoch(report["created_utc"]), "report", f"{report['category']} — {entry['sender']}", entry,
                [subject["lat"], subject["lon"]], source="Analyst report; unverified concern")
    return sorted(events, key=lambda row: (row["t"], row["kind"]))


def _motion(track):
    """Derive motion from received positions where speed/course are unavailable."""
    result, segment = [], 0
    for i, fix in enumerate(track):
        point = dict(fix)
        if i:
            previous = track[i - 1]
            dt = fix["t"] - previous["t"]
            continuous = (dt <= MAX_GAP_S and fix.get("stream_id") == previous.get("stream_id")
                          and fix.get("label") == previous.get("label")
                          and fix.get("source_segment") == previous.get("source_segment"))
            if not continuous or result[-1].get("invalid_motion"):
                segment += 1
            if continuous:
                speed = distance_nm(previous, fix) * 3600 / dt
                lat1, lat2 = math.radians(previous["lat"]), math.radians(fix["lat"])
                dl = math.radians(fix["lon"] - previous["lon"])
                bearing = math.degrees(math.atan2(math.sin(dl) * math.cos(lat2),
                    math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dl))) % 360
                point.setdefault("sog_kn", speed)
                point.setdefault("cog_deg", bearing)
                if point.get("sog_kn") is None:
                    point["sog_kn"] = speed
                if point.get("cog_deg") is None:
                    point["cog_deg"] = bearing
                if speed > 80:
                    point["invalid_motion"] = True
                    segment += 1
        point["motion_segment"] = segment
        result.append(point)
    return result


def _runs(samples, predicate):
    runs, current = [], []
    for sample in samples:
        if current and (sample["t"] - current[-1]["t"] > MAX_GAP_S or sample["streams"] != current[-1]["streams"]):
            runs.append(current)
            current = []
        if predicate(sample):
            current.append(sample)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def pair_review(vessels, now, *, anchorages=(), port_distance=None):
    """Review selected tracks (at most 40); match observations within 60 seconds.

    No interpolation, gap bridging, cross-provenance pairs or automatic score.
    Port/anchorage encounters are retained as context-only, not review leads.
    """
    if len(vessels) > 40:
        raise ValueError("Select at most 40 vessels for an encounter review")
    from argus.detectors.ais_spoofing import nearest_port_nm
    port_distance = port_distance or nearest_port_nm
    prepared = []
    for vessel in vessels:
        track = _motion([f for f in valid_track(vessel, now) if f["t"] >= now - PAIR_WINDOW_S])
        prepared.append((vessel, track))
    results = []
    for index, (left, a) in enumerate(prepared):
        for right, b in prepared[index + 1:]:
            if left.get("label") != right.get("label") or str(left["mmsi"]) == str(right["mmsi"]):
                continue
            times, samples, used = [f["t"] for f in b], [], set()
            for p in a:
                j = bisect_right(times, p["t"]) - 1
                if j < 0 or j in used or p["t"] - times[j] > MAX_SKEW_S:
                    continue
                q = b[j]
                used.add(j)
                if p.get("invalid_motion") or q.get("invalid_motion"):
                    continue
                if p.get("label", left["label"]) != left["label"] or q.get("label", right["label"]) != right["label"]:
                    continue
                samples.append({"t": p["t"], "a": p, "b": q, "distance_nm": distance_nm(p, q),
                                "streams": (p.get("stream_id"), q.get("stream_id"), p["motion_segment"], q["motion_segment"])})

            def parallel(s):
                x, y = s["a"], s["b"]
                values = [x.get("sog_kn"), y.get("sog_kn"), x.get("cog_deg"), y.get("cog_deg")]
                if any(v is None or not math.isfinite(v) for v in values):
                    return False
                return (s["distance_nm"] <= 1 and min(values[:2]) >= 3 and max(values[:2]) <= 80
                        and abs(values[0] - values[1]) <= 2 and abs((values[2] - values[3] + 180) % 360 - 180) <= 15)

            def slow(s):
                speeds = [s[k].get("sog_kn") for k in ("a", "b")]
                return s["distance_nm"] <= .5 and all(v is not None and 0 <= v <= 2 for v in speeds)

            close_runs = [r for r in _runs(samples, lambda s: s["distance_nm"] <= .5)
                          if len(r) >= 3 and r[-1]["t"] - r[0]["t"] >= 120]
            repeated = []
            for run in close_runs:
                if not repeated:
                    repeated.append(run)
                    continue
                previous = repeated[-1][-1]
                between = [s for s in samples if previous["t"] <= s["t"] <= run[0]["t"]]
                continuous = all(y["t"] - x["t"] <= MAX_GAP_S and x["streams"] == y["streams"]
                                 for x, y in zip(between, between[1:]))
                if not continuous:
                    repeated = [run]
                elif run[0]["t"] - previous["t"] >= 600 and any(s["distance_nm"] > 1 for s in between):
                    repeated.append(run)
            kinds = [("Parallel travel", [r for r in _runs(samples, parallel) if r[-1]["t"] - r[0]["t"] >= 1200]),
                     ("Possible rendezvous", [r for r in _runs(samples, slow) if r[-1]["t"] - r[0]["t"] >= 900]),
                     ("Repeated close approaches", [sum(repeated, [])] if len(repeated) >= 3 else [])]
            for kind, runs in kinds:
                for run in runs:
                    context = set()
                    for sample in (run[0], run[len(run) // 2], run[-1]):
                        for point in (sample["a"], sample["b"]):
                            near = port_distance(point["lat"], point["lon"])
                            if near is not None and near <= 3:
                                context.add("within 3 nm of a bundled port")
                            if any(distance_nm(point, area) <= area.get("radius_nm", 3) for area in anchorages):
                                context.add("inside a supplied anchorage")
                    results.append({"kind": kind, "vessels": [str(left["mmsi"]), str(right["mmsi"])],
                        "names": [left.get("name", str(left["mmsi"])), right.get("name", str(right["mmsi"]))],
                        "label": left["label"], "start": run[0]["t"], "end": run[-1]["t"],
                        "min_distance_nm": min(s["distance_nm"] for s in run), "samples": run,
                        "status": "Context only" if context else "For review",
                        "context": sorted(context), "note": "Rule thresholds are assumptions. Association and intent are unconfirmed."})
    return sorted(results, key=lambda r: (r["status"] != "For review", -r["end"], r["vessels"]))
