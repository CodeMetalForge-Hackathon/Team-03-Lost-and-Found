"""After-action review from the evidence chain (+ dog coverage + map state if present).

  time_to_first_contact_s : first contact_new  - mission start (mission_start record, else first detection)
  time_to_confirm_s       : contact_confirmed - that contact's first_seen, per confirmed contact
  area_covered_m2         : dog runs' cells with POD >= 0.5 (night/data/dog/*/layers.json, latest real run first)
  probability_captured    : sum of prior mass x POD over searched cells (from night/map/state.json, written
                            by the map service), and per hour of mission time
Every number is recomputed from files on each call; nothing is cached.

  python aar.py            # prints JSON and a short text table
"""
from __future__ import annotations
import json, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
NIGHT = HERE.parent
sys.path.insert(0, str(HERE))
from fuse import CHAIN, verify_chain  # noqa: E402


def _ts(s):
    return datetime.fromisoformat(s).timestamp()


def compute() -> dict:
    recs = [json.loads(x) for x in CHAIN.read_text().splitlines()] if CHAIN.exists() else []
    start = next((r["payload"]["t"] for r in recs if r["type"] == "mission_start"), None)
    dets = [r for r in recs if r["type"] == "detection"]
    if start is None and dets:
        start = min(r["payload"]["t"] for r in dets)
    news = [r for r in recs if r["type"] == "contact_new"]
    conf = [r for r in recs if r["type"] == "contact_confirmed"]
    first_seen = {r["payload"]["contact"]["contact_id"]: r["payload"]["contact"]["first_seen"] for r in news}
    ttfc = round(min(first_seen.values()) - start, 1) if (first_seen and start) else None
    ttc = [{"contact_id": r["payload"]["contact"]["contact_id"], "operator": r["payload"]["operator_id"],
            "s": round(_ts(r["ts"]) - first_seen[r["payload"]["contact"]["contact_id"]], 1)}
           for r in conf if r["payload"]["contact"]["contact_id"] in first_seen]
    end = max([_ts(r["ts"]) for r in recs] or [start or 0])
    hours = max((end - start) / 3600, 1e-9) if start else None
    area = None; area_src = None
    runs = sorted(NIGHT.glob("data/dog/*/layers.json"), key=lambda p: (json.loads(p.read_text()).get("synthetic", False), -p.stat().st_mtime))
    if runs:
        L = json.loads(runs[0].read_text()); area = L["coverage"]["area_m2_pod_ge_0_5"]
        area_src = runs[0].parent.name + (" (SYNTHETIC)" if L.get("synthetic") else "")
    pc = None; persona = None
    st = NIGHT / "map/state.json"
    if st.exists():
        S = json.loads(st.read_text()); pc = S.get("probability_captured"); persona = S.get("persona")
    return {"chain": verify_chain(), "mission_start": start, "detections": len(dets), "contacts": len(news),
            "confirmed": len(conf), "time_to_first_contact_s": ttfc, "time_to_confirm": ttc,
            "mission_hours": round(hours, 4) if hours else None,
            "area_covered_m2": area, "area_source": area_src,
            "probability_captured": pc, "probability_persona": persona,
            "probability_captured_per_hour": round(pc / hours, 4) if (pc is not None and hours) else None}


if __name__ == "__main__":
    r = compute(); print(json.dumps(r, indent=1))
