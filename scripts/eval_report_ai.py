#!/usr/bin/env python3
"""Evaluate the report assistant on fixed replay stories, offline by default.

For each story the Brain board item is scored at the end of its track and an
evidence pack is built without the panel (no incident or responders). Offline,
the template draft is checked by code. With --live, Draft with AI and Check
report call TensorX (paid; about $0.003 reserved per call, settled at the
reported cost under the $2 report budget; repeats are free from the cache).

It reports, per story: which draft was used, whether the AI reply matched the
schema, the validation result, whether every cited evidence ID exists, the
code check of the inserted text, the AI check's findings and dropped findings,
latency and cost. These are counts on six stories, not an accuracy measure.
"""

import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus import report_ai  # noqa: E402
from argus.brain_board import build_board  # noqa: E402
from argus.report_ai import (build_pack, budget, check_all, check_report, draft_report, request_json,  # noqa: E402
                             template_draft, validate_draft)

STORIES = (("SIM-53", "normal transit"), ("SIM-50", "cable risk: slowing across EWIC"),
           ("SIM-51", "cable risk: holding, then anchoring"), ("SIM-41", "dark vessel: AIS gap, radar contact"),
           ("SIM-49", "faulty AIS data"), ("SIM-55", "wrong destination"))


def snapshot(item):
    identifier = str(item["alert"]["mmsi"]) if item.get("exercise") else str(item["id"])
    return {"id": identifier, "name": item["name"], "label": item["label"], "lat": item["lat"], "lon": item["lon"]}


def packs():
    scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
    alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
    items = {item["id"]: item for item in build_board(scenario, alerts)}
    return [(identifier, story, build_pack(snapshot(items[identifier]), items[identifier], {}))
            for identifier, story in STORIES]


def offline_row(identifier, story, pack):
    draft = template_draft(pack)
    code = check_report(pack, draft["text"], draft["category"])
    known = {fact["id"] for fact in pack["facts"]}
    return {"id": identifier, "story": story, "level": pack["level"]["name"], "facts": len(pack["facts"]),
            "draft": "template", "chars": len(draft["text"]), "category": draft["category"],
            "evidence_ok": set(draft["evidence"]) <= known, "code_findings": len(code["findings"])}


def live_row(identifier, story, pack, root):
    row = {"id": identifier, "story": story, "level": pack["level"]["name"], "facts": len(pack["facts"])}
    try:
        value, meta = request_json("draft", pack, root=root)
        verdict = validate_draft(pack, value)
        row.update(schema_ok=verdict.get("problems") != ["The AI reply does not match the draft schema"],
                   draft_valid=verdict["ok"], problems=verdict.get("problems", []),
                   draft_latency_s=meta["latency_s"], draft_cost_usd=meta["cost_usd"], draft_cached=meta["cached"],
                   draft_tokens=meta["usage"])
        cited = value.get("evidence") if isinstance(value, dict) else None
        row["evidence_ok"] = isinstance(cited, list) and set(cited) <= {fact["id"] for fact in pack["facts"]}
    except (ValueError, OSError) as error:
        row.update(schema_ok=None, draft_valid=False, problems=[f"AI not run: {error}"])
    draft = draft_report(pack, root=root)  # the same cached reply, or the template when AI failed
    row.update(draft=draft["method"], chars=len(draft["text"]), category=draft["category"])
    result = check_all(pack, draft["text"], draft["category"], root=root)
    row["code_findings"] = len(result["code"]["findings"])
    ai = result["ai"]
    if "unavailable" in ai:
        row["ai_check"] = f"not run: {ai['unavailable']}"
    else:
        row.update(ai_findings=[f"{f['kind']}: {f['problem']}" for f in ai["findings"]], ai_dropped=ai["rejected"],
                   check_latency_s=ai["meta"]["latency_s"], check_cost_usd=ai["meta"]["cost_usd"],
                   check_cached=ai["meta"]["cached"])
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="call TensorX (paid) instead of the offline template")
    parser.add_argument("--root", type=Path, default=report_ai.AI_ROOT, help="report AI ledger and cache folder")
    args = parser.parse_args()
    before = budget(args.root)
    rows = [live_row(*entry, args.root) if args.live else offline_row(*entry) for entry in packs()]
    after = budget(args.root)
    summary = {"mode": "live" if args.live else "offline", "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "rows": rows, "ledger_before": before, "ledger_after": after}
    out = args.root / f"eval-{summary['mode']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
