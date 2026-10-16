"""Real alerts from live AIS in the Incidents panel (D107).

``argus.live_alerts`` (D104) runs the alert rules on real ships near the cable
routes. ``RealAlertFeed`` asks it every five minutes on a worker thread, and
``RealAlerts`` keeps what the panel needs between answers:

* An alert is one ship, ``REAL-<MMSI>``, for as long as the rules keep raising
  it (an episode). Its band is its level. It stays out of the exercise replay,
  because its times are real.
* Only a human sets its status. Opening it marks it Reviewed; Acknowledge,
  Escalate and Reject come from the review window. Each is signed into the
  decision log (D103), and after a restart a decision made during the current
  episode is restored from it, but only if the log verifies.
* A level rise after a decision asks for review again. A rise after Rejected
  reopens the alert, so a rejection never hides a worse situation.
* When the rules stop raising an alert nobody opened, it stays in its band as
  "cleared · not reviewed" (it latches). Once opened or decided, a cleared alert
  moves to Closed. Raised again within 30 min, it continues its episode; later,
  it is a new one.

No tkinter here: ``RealAlertFeed`` schedules through the board's ``after``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import threading
import time

from argus import live_alerts, supabase_ais
from argus.levels import LEVEL_NAMES, RANK

TAG = "AIS · REAL"
EPISODE_GAP_S = 30 * 60  # raised again within this, an alert continues its episode
FORGET_S = 6 * 3600  # a cleared alert is dropped after this; live_alerts keeps 6 h of fixes
UNLINKED_RETRY_S = 30  # how soon a computer that is not linked to the database is checked again
DECIDED = ("Reviewed", "Acknowledged", "Escalated", "Rejected")
_network = False  # Only run_gui.main allows the feed, so tests and --check never reach the database.


def allow_network() -> None:
    global _network
    _network = True


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hhmm(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%H:%MZ")


def parse_time(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def check(tracks, workspace_root, now: float | None = None) -> dict:
    """One check on the worker thread: the rules on real ships near the routes, or why they could not run."""
    if not supabase_ais.linked(workspace_root):
        return {"state": "unlinked"}
    now = time.time() if now is None else now
    started = time.perf_counter()
    try:
        stats = tracks.refresh(now)
        vessels = tracks.vessels(now)
        items = live_alerts.assess(vessels, now)
    except (ValueError, OSError) as error:
        text = str(error)[:200] or type(error).__name__
        if "HTTP 404" in text:
            text += "; the database function argus_recent_tracks may not be installed yet"
        return {"state": "error", "error": text, "checked_t": now}
    skipped = sum(getattr(tracks, "skipped", {}).values())
    return {"state": "ok", "items": items, "checked_t": now, "ships": stats["ships"], "near": len(vessels) + skipped,
            "skipped": skipped, "assessed": len(vessels), "truncated": stats["truncated"],
            "seconds": time.perf_counter() - started}


def as_panel_item(raw: dict) -> dict:
    """The board's shape: the track as (lat, lon) points; the AIS fixes stay under ``fixes``."""
    fixes = raw.get("track") or []
    return {**raw, "fixes": fixes, "track": [(fix["lat"], fix["lon"]) for fix in fixes],
            "line_name": raw.get("line_name") or "No cable route named"}


class RealAlerts:
    """Real alerts between checks: band, status, episode and log, by alert id."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.state: dict[str, dict] = {}
        self.saved: dict[str, list[dict]] = {}  # decisions read from the signed log, oldest first
        self.feed = "idle"  # idle, loading, disabled, unlinked, remote, ok or error
        self.error: str | None = None
        self.problem: str | None = None  # why earlier decisions were not restored
        self.stats: dict = {}
        self.checked_t: float | None = None  # the last check that worked

    # ----- the signed log -------------------------------------------------------------
    def restore(self, log) -> None:
        """Read earlier decisions on real alerts from the signed log; a log that fails its check restores none."""
        try:
            verified = log.verify()
            records = log.records() if verified.ok else []
        except (OSError, ValueError):
            verified, records = None, []
        if verified is None or not verified.ok:
            self.problem = ("The signed decision log did not verify, so earlier decisions on real alerts were "
                            "not restored.")
            return
        for record in records:
            t = parse_time(record.get("time"))
            if record.get("kind") == "decision" and record.get("real") and record.get("action") in DECIDED and t:
                self.saved.setdefault(record.get("alert"), []).append({**record, "t": t})

    # ----- checks ---------------------------------------------------------------------
    def update(self, result: dict, now: float | None = None) -> dict[str, str]:
        """Fold one check in; returns {alert id: "new", "rose" or "reopened"} for the status line."""
        self.feed = result.get("state", "error")
        if self.feed != "ok":
            # The last good alerts stay; the status text says how old they are.
            self.error = result.get("error")
            return {}
        now = result["checked_t"] if now is None else now
        self.error, self.checked_t = None, result["checked_t"]
        self.stats = {key: result.get(key) for key in ("ships", "near", "skipped", "assessed", "truncated", "seconds")}
        events, seen = {}, set()
        for raw in result["items"]:
            item = as_panel_item(raw)
            identifier = item["id"]
            seen.add(identifier)
            state = self.state.get(identifier)
            if state is None or (state["cleared_t"] is not None and now - state["cleared_t"] > EPISODE_GAP_S):
                state = self._open(item)
                events[identifier] = "new"
            else:
                before = self.items[identifier]["assessment"]
                if state["cleared_t"] is not None:
                    state["cleared_t"] = None
                    state["log"].append((now, "Raised again by the rules"))
                if item["assessment"]["level"] != before["level"]:
                    rose = RANK[item["assessment"]["level"]] > RANK[before["level"]]
                    state["log"].append((now, f"Level {'rose' if rose else 'fell'} to "
                                              f"{item['assessment']['level_name']} {item['assessment']['score']}"))
                    if rose:
                        events[identifier] = "rose"
            self.items[identifier] = item
            if self._risen(identifier, now):
                events[identifier] = "reopened"
        for identifier, state in list(self.state.items()):
            if identifier in seen:
                continue
            if state["cleared_t"] is None:
                state["cleared_t"] = now
                state["log"].append((now, "Cleared: the rules no longer raise it"))
            elif now - state["cleared_t"] > FORGET_S:
                del self.state[identifier], self.items[identifier]
        return events

    def _open(self, item: dict) -> dict:
        """A new episode; decisions signed during it before a restart still stand."""
        old = self.state.get(item["id"])
        state = {"status": "New", "reason": None, "to": None, "decided_rank": None, "review_again": False,
                 "cleared_t": None, "log": old["log"] if old else []}
        state["log"].append((item["raised_t"], f"Raised at {item['assessment']['level_name']} "
                                               f"{item['assessment']['score']}: {item['title']}"))
        self.state[item["id"]] = state
        for record in self.saved.get(item["id"], []):
            if record["t"] >= item["raised_t"] - EPISODE_GAP_S:
                self._apply(state, record["action"], f"{record.get('detail') or record['action']} (signed log)",
                            record["t"], record.get("reason"), record.get("to"), RANK.get(record.get("level")))
        return state

    def _risen(self, identifier: str, now: float) -> bool:
        """Above the level of the last decision: review again; reopened if that decision was Rejected."""
        state, level = self.state[identifier], self.items[identifier]["assessment"]["level"]
        if state["decided_rank"] is None or RANK[level] <= state["decided_rank"] or state["review_again"]:
            return False
        state["review_again"] = True
        if state["status"] != "Rejected":
            return False
        state["status"], state["reason"] = "New", None
        state["log"].append((now, f"Reopened: the level rose to {LEVEL_NAMES[level]} after the rejection"))
        return True

    # ----- decisions ------------------------------------------------------------------
    def decide(self, identifier: str, status: str, text: str, reason: str | None = None, to: str | None = None,
               now: float | None = None) -> None:
        level = self.items[identifier]["assessment"]["level"]
        self._apply(self.state[identifier], status, text, time.time() if now is None else now, reason, to, RANK[level])

    @staticmethod
    def _apply(state: dict, status: str, text: str, t: float, reason, to, rank) -> None:
        state.update(status=status, reason=reason if status == "Rejected" else None,
                     to=to if status == "Escalated" else None, decided_rank=rank, review_again=False)
        state["log"].append((t, text))

    # ----- what the panel shows -------------------------------------------------------
    def ordered(self) -> list[str]:
        """Alert ids: most severe first, then the higher score, then the newest."""
        def key(identifier):
            item = self.items[identifier]
            return (-RANK[item["assessment"]["level"]], -item["assessment"]["score"], -item["raised_t"], identifier)
        return sorted(self.items, key=key)

    def band(self, identifier: str) -> str:
        state = self.state[identifier]
        if state["status"] == "Rejected" or (state["cleared_t"] is not None and state["status"] != "New"):
            return "closed"
        return self.items[identifier]["assessment"]["level"]

    def attention(self, identifier: str) -> bool:
        state = self.state[identifier]
        return state["review_again"] or (state["cleared_t"] is not None and state["status"] == "New")

    def detail(self, identifier: str) -> str:
        """Status line: review again, cleared, the analyst's status, then the level."""
        item, state = self.items[identifier], self.state[identifier]
        parts = ["⚠ Review again"] if state["review_again"] else []
        latched = state["cleared_t"] is not None and state["status"] == "New"
        if state["cleared_t"] is not None:
            parts.append(f"Cleared {hhmm(state['cleared_t'])}" + (" · not reviewed" if latched else ""))
        if state["status"] == "Escalated" and state["to"]:
            parts.append(f"Escalated · {state['to']}")
        elif state["status"] == "Rejected" and state["reason"]:
            parts.append(f"Rejected · {state['reason']}")
        elif not latched:
            parts.append(state["status"])
        parts.append(f"{item['assessment']['level_name']} {item['assessment']['score']}")
        return " · ".join(parts)

    def log_lines(self, identifier: str) -> list[tuple[str, str]]:
        return [(hhmm(t), text) for t, text in self.state[identifier]["log"]]

    def open_count(self) -> int:
        return sum(1 for identifier in self.items if self.band(identifier) != "closed")

    def status_text(self) -> str:
        """What was checked and how fresh it is, for the SOURCES block."""
        stats = self.stats
        if self.feed == "disabled":
            text = "Off on this computer (ARGUS_REAL_ALERTS=0)."
        elif self.feed == "unlinked":
            text = ("Not running: this computer is not linked to the team AIS database. The rules need the "
                    "recorded tracks, not only the live map positions.")
        elif self.feed == "remote":
            text = "Not shown through the SOC connection yet: they run on a computer linked to the team database."
        elif self.checked_t is None:
            text = (f"Last check failed: {self.error}" if self.feed == "error"
                    else "Loading the last 3 h of AIS from the team database…")
        else:
            text = (f"{stats.get('ships') or 0} ships in Irish waters in the last 3 h · {stats.get('near') or 0} near "
                    f"a cable route · {stats.get('skipped') or 0} harbour craft left out\n"
                    f"{stats.get('assessed') or 0} assessed · {len(self.items)} alerts · checked "
                    f"{hhmm(self.checked_t)} ({stats.get('seconds') or 0:.1f} s), every 5 min")
            if stats.get("truncated"):
                text += "\nThe database answer was cut short; some ships may be missing."
            if self.feed == "error":
                text += f"\nLast check failed: {self.error}. Alerts shown are from {hhmm(self.checked_t)}."
        if self.problem:
            text += "\n" + self.problem
        return text + "\nRule outcomes on public AIS and illustrative routes, for review; never evidence of intent."


class RealAlertFeed:
    """Every five minutes, ``check`` on a daemon thread; the answer goes to the board on the Tk thread."""

    def __init__(self, board, workspace_root, tracks=None):
        self.board, self.workspace_root, self.tracks = board, workspace_root, tracks
        self.timer = None
        self.running: tuple[threading.Thread, dict] | None = None
        self.next_t = 0.0
        self.started = False

    def start(self) -> bool:
        """Begin checking, unless this process stays off the network (tests) or ARGUS_REAL_ALERTS=0."""
        if os.environ.get("ARGUS_REAL_ALERTS") == "0":
            self.board.refresh_real({"state": "disabled"})
            return False
        if not _network or self.started:
            return False
        self.started = True
        self.board.refresh_real({"state": "loading"})
        self.timer = self.board.app.root.after(1500, self.poll)
        return True

    def poll(self) -> None:
        self.timer = None
        if self.running is not None and not self.running[0].is_alive():
            result = self.running[1].get("result") or {"state": "error", "error": "Live AIS check stopped",
                                                       "checked_t": time.time()}
            self.running = None
            if result["state"] == "unlinked":
                self.next_t = time.monotonic() + UNLINKED_RETRY_S
            self.board.refresh_real(result)
        if self.running is None and time.monotonic() >= self.next_t:
            self.next_t = time.monotonic() + live_alerts.REFRESH_S
            if getattr(self.board.app, "soc_client", None) is not None:
                self.board.refresh_real({"state": "remote"})
            else:
                self.launch()
        self.timer = self.board.app.root.after(1000, self.poll)

    def launch(self) -> None:
        box: dict = {}

        def run():
            try:
                if self.tracks is None:
                    self.tracks = live_alerts.LiveTracks()
                box["result"] = check(self.tracks, self.workspace_root)
            except Exception as error:  # A fault in one rule must not stop the panel's checks
                box["result"] = {"state": "error", "error": f"Live AIS check failed ({type(error).__name__})",
                                 "checked_t": time.time()}
        # A daemon thread: a check still waiting for the database never holds up closing the app.
        thread = threading.Thread(target=run, name="argus-real-alerts", daemon=True)
        self.running = (thread, box)
        thread.start()

    def check_now(self) -> None:
        """Check at the next poll, e.g. after the database was linked."""
        self.next_t = 0.0

    def close(self) -> None:
        if self.timer is not None:
            try:
                self.board.app.root.after_cancel(self.timer)
            except Exception:  # Tk may already be gone
                pass
            self.timer = None
