"""Per-frame table of what the demo shows for each synthetic frame (deterministic simulated tilt draw = app.tilt_noise
seeded by crc32(demo id)). Writes results/demo_synth_table.json. Used to pick a REPRESENTATIVE (median-draw) demo frame."""
import json, math, pathlib, sys, zlib, os
os.environ["SKYFIX_NO_WARM"] = "1"
ROOT = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(ROOT))
import numpy as np, solver_stars as S
from app import CAT, tilt_noise, err_km
rows = []
for k, it in CAT.items():
    if it["set"] != "synthetic": continue
    g, applied = tilt_noise(it["gravity"], 0.3, zlib.crc32(k.encode()))
    ex = S.solve(it["path"], utc=it["utc"], gravity=it["gravity"], tilt=0.0, elevation_m=it["elevation_m"])
    r = S.solve(it["path"], utc=it["utc"], gravity=g, tilt="braced", elevation_m=it["elevation_m"])
    e = err_km(r["fix"]["lat"], r["fix"]["lon"], it["truth"])
    rows.append(dict(id=k, tilt_draw_deg=applied, exact_err_km=err_km(ex["fix"]["lat"], ex["fix"]["lon"], it["truth"]), err_km=e,
                     ring_km=r["fix"]["ring_km"], ring95_km=r["fix"]["ring95_km"], in_ring=e <= r["fix"]["ring_km"], in_ring95=e <= r["fix"]["ring95_km"]))
rows.sort(key=lambda x: x["tilt_draw_deg"])
(ROOT / "results/demo_synth_table.json").write_text(json.dumps(rows, indent=1))
print("median draw frame:", rows[len(rows)//2])
print("in ring:", sum(r["in_ring"] for r in rows), "in ring95:", sum(r["in_ring95"] for r in rows), "of", len(rows))
for r in rows:
    if r["id"].startswith("synth:boston"): print(r)
