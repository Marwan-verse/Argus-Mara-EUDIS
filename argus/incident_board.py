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
"""

from __future__ import annotations

from argus import incidents
from argus.levels import RANK

# Below OPEN_LEVEL a contact is watched, not an incident.
OPEN_RANK = RANK[incidents.OPEN_LEVEL]


def vessel_key(item: dict) -> str:
    """Incident key of a board item: the scenario MMSI for the exercise, else the board ID."""
    if item.get("exercise"):
        return str(item["alert"]["mmsi"])
    return str(item["id"])


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
