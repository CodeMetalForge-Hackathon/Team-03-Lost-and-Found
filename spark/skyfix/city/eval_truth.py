"""Ground truth for the two Boston photos. Truth (stated by the photographer): 60 State Street, 14th floor; 13.7 ft/floor for
this building -> camera ~190 ft / 58 m above street. Reads results/taps_<photo>.json ({taps, horizon, tapped_by}) and runs
the exact solve path of the running server (POST /api/solve on :8133). Writes results/ground_truth.json.
Usage: ~/forge/.venv/bin/python eval_truth.py
"""
import json, ssl, urllib.request
from pathlib import Path
C = Path(__file__).resolve().parent
TRUTH = {"lat": 42.3590, "lon": -71.0565, "h_above_street_m": 58.0, "floor": 14, "ft_per_floor": 13.7}
ctx = ssl._create_unverified_context()
runs = []
for f in sorted((C / "results").glob("taps_*.json")):
    t = json.loads(f.read_text())
    body = {"photo": t["photo"], "taps": t["taps"], "horizon": t.get("horizon"), "ft_per_floor": TRUTH["ft_per_floor"]}
    r = urllib.request.Request("https://127.0.0.1:8133/api/solve", data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    try:
        s = json.loads(urllib.request.urlopen(r, context=ctx, timeout=60).read())
    except urllib.error.HTTPError as e:
        runs.append({"photo": t["photo"], "error": e.read().decode()[:300]}); continue
    h = (s.get("height") or {}).get("primary")
    runs.append({"photo": t["photo"], "tapped_by": t.get("tapped_by"), "landmarks": [x["name"] for x in s["landmarks"]],
                 "lat": round(s["lat"], 6), "lon": round(s["lon"], 6), "position_error_m": s["vs_reference"]["distance_m"],
                 "ring_m": s["ring_m"], "inside_ring": s["vs_reference"]["inside_ring"], "heading_deg": s["heading_deg"],
                 "h_above_street_m": h and h["h_above_ground_m"], "height_error_m": h and round(h["h_above_ground_m"] - TRUTH["h_above_street_m"], 1),
                 "floor_est": h and h["floor_est"], "ft_per_floor": TRUTH["ft_per_floor"], "sun": s.get("sun"), "warnings": s["warnings"],
                 "lens": s["lens"], "residuals_deg": s["residuals_deg"], "camera": s["camera"]})
out = {"truth": TRUTH, "runs": runs, "note": "position error = distance from the solved fix to 60 State St (42.3590, -71.0565); "
       "the truth point is the building, the camera can be anywhere on that floor (footprint ~60 m across)."}
(C / "results/ground_truth.json").write_text(json.dumps(out, indent=1)); print(json.dumps(runs, indent=1)[:3000])
