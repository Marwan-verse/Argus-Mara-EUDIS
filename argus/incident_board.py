"""Incidents for the alert panel: one ``argus.incidents`` card per board contact.

The panel (``desktop_alerts``) scores its contacts through ``argus.brain_board``
at every tick. This module folds those scores into ``argus.incidents`` and
reports what changed, so the panel can show one updatable incident per vessel
instead of one row per alert. No tkinter here, so it is tested without a display.

* A contact at Medium or above has an open incident; Low and None contacts are
  observations ("watching"), not incidents.
* The exercise contact is keyed by its scenario MMSI, simulated contacts by
  their board ID (``SIM-41``), so incident IDs read ``INC-999000001-1`` and
  ``INC-SIM-41-1``.
* Status changes go through ``argus.incidents.set_status`` only.
* ``Replay`` runs the board on the exercise replay clock: forwards in steps,
  and backwards by rebuilding from the start and re-applying the analyst's
  earlier decisions (``argus.incidents`` itself never goes back in time).
* At every replay step ``Replay`` also asks ``argus.responders`` who can reach
  each contact at Medium or above. If no physical asset arrives before the
  earliest line ETA, ``no_response_in_time`` goes into the contact's
  observations and it is scored once more (observations, then responders, then
  one assessment; responders never depend on the level, so this never loops).
* ``Replay.send`` records a simulated human decision to send a physical asset
  to an incident. The asset is then busy for every other incident until
  ``Replay.recall`` or until its incident is rejected (closed); the board is
  scored again at once, so another incident that relied on it can rise.
  Sends and recalls are decisions like a status change, so a rewind replays them.
"""

from __future__ import annotations

from argus import incidents, responders
from argus.brain_board import reassess, rescore_exercise, update
from argus.levels import LEVEL_NAMES, RANK
from argus.prediction import position_at

# Below OPEN_LEVEL a contact is watched, not an incident.
OPEN_RANK = RANK[incidents.OPEN_LEVEL]
# Replay step: fine enough for 30 min quiet checks, cheap enough to rebuild a whole replay.
STEP_S = 60
EVENT_TEXT = {"opened": "Incident {id} opened at {level}", "raised": "Level raised to {level}",
              "review_again": "Level rose after review: review again",
              "quiet": f"Quiet {incidents.QUIET_CLOSE_S // 60} min below Medium: close?"}


def vessel_key(item: dict) -> str:
    """Incident key of a board item: the scenario MMSI for the exercise, else the board ID."""
    if item.get("exercise"):
        return str(item["alert"]["mmsi"])
    return str(item["id"])


def deadline_s(item: dict, now: float):
    """Replay time of the item's earliest possible line contact: now if in the corridor, None if no line ETA.

    The exercise contact's ETA is measured at its detector finding's time;
    simulated ETAs count down with the board, so they are measured from now.
    """
    obs = item.get("observations") or {}
    if obs.get("in_corridor"):
        return now
    if obs.get("eta_min") is None:
        return None
    if item.get("exercise"):
        times = [finding["t"] + finding["eta_min"] * 60 for finding in item.get("findings", [])
                 if finding.get("cable_id") and finding.get("t") is not None and finding.get("eta_min") is not None]
        if times:
            return min(times)
    return now + obs["eta_min"] * 60


def feed(items: list[dict]) -> list[dict]:
    """Board items in the shape ``argus.incidents.update_incidents`` reads."""
    return [{"mmsi": vessel_key(item), "name": item.get("name"), "label": item.get("label", "simulated"),
             "cable_id": item.get("cable_id") or item.get("line_id"), "assessment": item["assessment"]}
            for item in items]


class Tracker:
    """Incident state for the board's contacts, stepped with the board's clock."""

    def __init__(self):
        self.state = incidents.new_state()

    def _snapshot(self) -> dict:
        return {key: (inc["id"], inc["level"], inc["needs_review_again"], inc["suggest_close"])
                for key, inc in self.state["open"].items()}

    def step(self, items: list[dict], now: int) -> dict[str, list[str]]:
        """Fold one board step into the incidents; return ``{item id: [event, ...]}``.

        Events: ``opened`` (a new incident), ``raised`` (its level rose),
        ``review_again`` (it rose after a human decision) and ``quiet`` (30 min
        below Medium, so closing is suggested).
        """
        before = self._snapshot()
        incidents.update_incidents(self.state, feed(items), int(now))
        after = self._snapshot()
        events: dict[str, list[str]] = {}
        for item in items:
            key = vessel_key(item)
            if key not in after:
                continue
            found = []
            old, new = before.get(key), after[key]
            if old is None or old[0] != new[0]:
                found.append("opened")
            else:
                if RANK[new[1]] > RANK[old[1]]:
                    found.append("raised")
                if new[2] and not old[2]:
                    found.append("review_again")
                if new[3] and not old[3]:
                    found.append("quiet")
            if found:
                events[item["id"]] = found
        return events

    def open_incident(self, item: dict) -> dict | None:
        return self.state["open"].get(vessel_key(item))

    def incident(self, item: dict) -> dict | None:
        """The vessel's open incident, else its most recently closed one, else None."""
        found = self.open_incident(item)
        if found is not None:
            return found
        key = vessel_key(item)
        closed = [inc for inc in self.state["closed"] if str(inc["mmsi"]) == key]
        return closed[-1] if closed else None

    def status(self, item: dict) -> str | None:
        """New/Reviewed/... for an open incident, "Rejected" for a closed one, None for a watched contact."""
        found = self.incident(item)
        if found is None:
            return None
        return found["status"] if self.open_incident(item) is not None else "Rejected"

    def decide(self, item: dict, status: str, reason: str | None = None) -> dict:
        """Record a human decision on the vessel's open incident (``KeyError`` if it has none)."""
        found = self.open_incident(item)
        if found is None:
            raise KeyError(f"{item['id']} has no open incident")
        return incidents.set_status(self.state, found["id"], status, reason)


class Replay:
    """Board items and their incidents at a replay time, moved forwards or backwards.

    ``start_s`` is the replay time the board's simulated countdowns start from
    (the exercise alert). A simulated contact appears ``raised_min_ago`` before
    it; the exercise vessel is always present and re-scored on its own track.
    """

    def __init__(self, items: list[dict], scenario: dict, start_s: float, step_s: int = STEP_S):
        self.items, self.scenario, self.start_s, self.step_s = items, scenario, int(start_s), step_s
        self.decisions: list[dict] = []
        self.fleet = responders.load_fleet()
        self.storm = False
        self._reset()

    def _reset(self) -> None:
        self.tracker = Tracker()
        self.now: int | None = None
        self.log: dict[str, list[tuple[int, str]]] = {}
        self.recipients: dict[str, str] = {}
        self.responses: dict[str, dict] = {}
        self.assignments: dict[str, dict] = {}  # asset ID -> {"incident", "item", "t"}

    @property
    def wind_kn(self) -> float:
        wind = self.fleet["wind"]
        return wind["storm_kn"] if self.storm else wind["normal_kn"]

    def position(self, item: dict):
        """Position function of the item: its scenario track (dark gaps predicted), else dead reckoning."""
        if item.get("exercise"):
            vessel = next(v for v in self.scenario["vessels"] if v["mmsi"] == item["alert"]["mmsi"])
            track, first = vessel["track"], vessel["track"][0]

            def at(t):
                fix = position_at(track, t)
                return (fix["lat"], fix["lon"]) if fix else (first["lat"], first["lon"])
            return at
        return responders.dead_reckoning(item["lat"], item["lon"], item.get("cog_deg"), item.get("sog_kn"),
                                         self.start_s)

    def respond(self, item: dict, t: int) -> dict:
        """Responders for one item at replay time t, given the current assignments and wind."""
        incident = self.tracker.open_incident(item)
        busy = {asset: given["incident"] for asset, given in self.assignments.items()}
        dispatched = {asset: given["t"] for asset, given in self.assignments.items()}
        return responders.assess_fleet(self.fleet, self.position(item), t, deadline_s(item, t), self.wind_kn,
                                       busy, incident["id"] if incident else None, dispatched)

    def _respond(self, t: int) -> None:
        """Responders for every present contact at Medium or above; flag and re-score those nobody reaches in time."""
        self.responses = {}
        for item in self.items:
            if t < self.appear_s(item):
                continue
            if item["observations"].pop("no_response_in_time", None):
                reassess(item)
            if RANK[item["assessment"]["level"]] < OPEN_RANK:
                continue
            result = self.responses[item["id"]] = self.respond(item, t)
            if result["no_response_in_time"]:
                item["observations"]["no_response_in_time"] = True
                reassess(item)

    def appear_s(self, item: dict) -> float:
        if item.get("exercise"):
            return float("-inf")
        return self.start_s - item.get("raised_min_ago", 0) * 60

    def present(self, item: dict) -> bool:
        return self.now is not None and self.now >= self.appear_s(item)

    def _note(self, identifier: str, t: int, text: str) -> None:
        self.log.setdefault(identifier, []).append((t, text))

    def _step(self, t: int) -> dict[str, list[str]]:
        update(self.items, t - self.start_s)
        for item in self.items:
            if item.get("exercise"):
                rescore_exercise(item, self.scenario, t)
        self.now = t
        self._respond(t)
        events = self.tracker.step([item for item in self.items if t >= self.appear_s(item)], t)
        by_id = {item["id"]: item for item in self.items}
        for identifier, found in events.items():
            incident = self.tracker.incident(by_id[identifier])
            for event in found:
                self._note(identifier, t, EVENT_TEXT[event].format(id=incident["id"],
                                                                 level=LEVEL_NAMES[incident["level"]]))
        return events

    def conflicts(self, item: dict, asset_id: str) -> list[dict]:
        """Other open incidents for which ``asset_id`` is the only physical asset arriving in time."""
        found = []
        for other in self.items:
            result = self.responses.get(other["id"])
            if other["id"] == item["id"] or not result or result["at_line"] or result["assigned"]:
                continue
            in_time = {row["id"] for row in result["rows"] if row["counts"] and row["in_time"]}
            if in_time == {asset_id}:
                found.append(other)
        return found

    def send(self, item: dict, asset_id: str) -> dict[str, list[str]]:
        """Send a physical asset to the item's open incident (a human decision); score again and return events.

        ``ValueError`` if the asset does not count as a responder or cannot go
        (out of range, grounded, already assigned); ``KeyError`` without an open incident.
        """
        asset = next((asset for asset in self.fleet["assets"] if asset["id"] == asset_id), None)
        if asset is None or not asset.get("counts"):
            raise ValueError(f"{asset_id} is not a physical responder")
        row = next((row for row in (self.responses.get(item["id"]) or {}).get("rows", []) if row["id"] == asset_id),
                   None)
        if row is None or row["status"] in ("unavailable", "assigned"):
            raise ValueError(f"{asset_id} cannot be sent: {row['reason'] if row else 'no responder estimate'}")
        verdict = ("" if row["margin_s"] is None else
                   f", in time (+{responders.minutes(row['margin_s'])} min)" if row["in_time"]
                   else f", {responders.minutes(-row['margin_s'])} min late")
        who = asset["name"] if asset_id in asset["name"] else f"{asset_id} ({asset['name']})"
        text = f"Sent {who}: eyes on in {responders.minutes(row['eta_s'])} min{verdict}"
        self._record({"action": "send", "asset": asset_id, "id": item["id"], "text": text})
        return self.refresh()

    def recall(self, item: dict, asset_id: str) -> dict[str, list[str]]:
        """Take an asset back from the item's incident; it is free for the others again. Score again."""
        self._record({"action": "recall", "asset": asset_id, "id": item["id"],
                      "text": f"Recalled {asset_id}; free for other incidents"})
        return self.refresh()

    def _record(self, decision: dict) -> None:
        decision = {"t": self.now, "status": None, "reason": None, "to": None, **decision}
        if not self._apply(decision):
            raise KeyError(f"{decision['id']}: cannot {decision['action']} {decision['asset']}")
        self.decisions.append(decision)

    def _apply_response(self, item: dict, decision: dict) -> bool:
        incident = self.tracker.open_incident(item)
        asset, given = decision["asset"], self.assignments.get(decision["asset"])
        if decision["action"] == "send":
            if incident is None or given is not None:
                return False
            self.assignments[asset] = {"incident": incident["id"], "item": item["id"], "t": decision["t"]}
        else:
            if given is None or given["item"] != item["id"]:
                return False
            del self.assignments[asset]
        if incident is not None:
            incident.setdefault("responses", []).append(
                {"t": decision["t"], "action": decision["action"], "asset": asset})
        self._note(item["id"], decision["t"], decision["text"])
        return True

    def _release(self, item: dict, t: int) -> list[str]:
        """Free the assets of a closed incident."""
        freed = [asset for asset, given in self.assignments.items() if given["item"] == item["id"]]
        for asset in freed:
            del self.assignments[asset]
            self._note(item["id"], t, f"{asset} released: incident closed")
        return freed

    def refresh(self) -> dict[str, list[str]]:
        """Score the current replay time again (after the wind or an assignment changed); return its events."""
        if self.now is None:
            return {}
        return self._step(self.now)

    def _apply(self, decision: dict) -> bool:
        item = next(item for item in self.items if item["id"] == decision["id"])
        if decision.get("action"):
            return self._apply_response(item, decision)
        try:
            self.tracker.decide(item, decision["status"], decision["reason"])
        except (KeyError, ValueError):
            return False
        if decision["status"] == "Escalated" and decision.get("to"):
            self.recipients[decision["id"]] = decision["to"]
        else:
            self.recipients.pop(decision["id"], None)
        self._note(decision["id"], decision["t"], decision["text"])
        if decision["status"] == "Rejected":
            self._release(item, decision["t"])
        return True

    def seek(self, t: float) -> tuple[dict[str, list[str]], bool]:
        """Move the board to replay time ``t``; return (events while moving forwards, whether it rewound).

        Going back rebuilds from the earlier of 0 and ``t``, re-applying decisions made up to ``t``;
        decisions made after ``t`` are dropped, as they had not happened yet.
        """
        t = int(t)
        if self.now == t:
            return {}, False
        if self.now is not None and t > self.now:
            events: dict[str, list[str]] = {}
            for moment in [*range(self.now + self.step_s, t, self.step_s), t]:
                for identifier, found in self._step(moment).items():
                    events.setdefault(identifier, []).extend(found)
            return events, False
        rewound = self.now is not None
        self._reset()
        self.decisions = [decision for decision in self.decisions if decision["t"] <= t]
        pending = sorted(self.decisions, key=lambda decision: decision["t"])
        origin = min(0, t)
        applied = False
        for moment in [*range(origin, t, self.step_s), t]:
            self._step(moment)
            applied = False
            while pending and pending[0]["t"] <= moment:
                applied = self._apply(pending.pop(0)) or applied
        if applied and self.assignments_changed_at(t):
            self.refresh()  # a send or recall at the last moment changes who reaches whom now
        return {}, rewound

    def assignments_changed_at(self, t: int) -> bool:
        return any(decision.get("action") or decision["status"] == "Rejected"
                   for decision in self.decisions if decision["t"] == t)

    def decide(self, item: dict, status: str, text: str, reason: str | None = None, to: str | None = None) -> dict:
        """Record a human decision at the current replay time (``KeyError`` with no open incident)."""
        decision = {"t": self.now, "id": item["id"], "status": status, "reason": reason, "to": to, "text": text}
        held = set(self.assignments)
        if not self._apply(decision):
            raise KeyError(f"{item['id']} has no open incident for {status}")
        self.decisions.append(decision)
        if held != set(self.assignments):
            self.refresh()  # a closed incident freed its assets for the others
        return self.tracker.incident(item)
