"""Person detector over NOAA ERI GeoTIFF tiles (native resolution, 640 px windows). venv_u84.
Usage: detect_noaa.py <weights> <tif_dir> <scene_tiles_dir> [--conf 0.25]
Writes <scene_tiles_dir>/detections.json with lat/lon boxes for the :8150 viewer."""
import sys, json, time, argparse
from pathlib import Path
import numpy as np, rasterio
from ultralytics import YOLO
sys.path.insert(0, str(Path(__file__).parent)); from detect_air import run
ap = argparse.ArgumentParser(); ap.add_argument("weights"); ap.add_argument("tifs"); ap.add_argument("scene")
ap.add_argument("--conf", type=float, default=0.25); a = ap.parse_args()
m = YOLO(a.weights); t0 = time.time(); dets = []; npx = 0; per = {}
for f in sorted(Path(a.tifs).glob("*.tif")):
    with rasterio.open(f) as d:
        arr = d.read([1, 2, 3]).transpose(1, 2, 0)[..., ::-1].copy(); T = d.transform
    npx += arr.shape[0] * arr.shape[1]
    bs = run(m, arr, 640, 0.2, 640, a.conf); per[f.name] = len(bs)
    for b in bs:
        w_, n_ = T * (b["x0"], b["y0"]); e_, s_ = T * (b["x1"], b["y1"])
        dets.append({"tile": f.name, "conf": round(b["conf"], 3), "w": w_, "n": n_, "e": e_, "s": s_})
    del arr
n60 = sum(1 for d in dets if d["conf"] >= 0.6)
out = {"dets": dets, "summary": {"weights": Path(a.weights).name, "tiles": len(per), "megapixels": round(npx / 1e6),
        "windows": "640 px native, 20% overlap", f"detections conf≥{a.conf}": len(dets), "detections conf≥0.60": n60,
        "runtime_s": round(time.time() - t0)},
       "note": f"Expected none: at this GSD a person is a few pixels. Result: {len(dets)} boxes at conf ≥ {a.conf} ({n60} at ≥ 0.60). Shown in red; they are unverified and not sent to fusion (this place is not the search grid)."}
Path(a.scene, "detections.json").write_text(json.dumps(out, indent=1)); print(json.dumps(out["summary"]), per)
