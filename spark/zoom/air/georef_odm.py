"""Georeference detection pixels in Aukerman photos through ODM/OpenSfM camera poses (ray → ground plane).

Usage: georef_odm.py <reconstruction.json> <dets.json> <out.json> [--conf 0.6]
OpenSfM: rotation = angle-axis world→camera, camera centre C = -Rᵀt (topocentric metres around reference_lla).
Pixel → normalised (OpenSfM convention, ignoring lens distortion, k1..k3 are small here) → bearing Rᵀ[x, y, 1]
→ intersect with z = median height of the sparse point cloud. Reports the ray-plane point and the distance to
the camera's ground nadir. Error sources: flat-ground assumption (sparse cloud 5–95 % spread is reported),
ignored distortion, GPS-aligned (not GCP) reconstruction.
"""
import sys, json, math, argparse
from pathlib import Path
import numpy as np
import cv2

R_E = 6371008.8
ap = argparse.ArgumentParser(); ap.add_argument("recon"); ap.add_argument("dets"); ap.add_argument("out")
ap.add_argument("--conf", type=float, default=0.6); a = ap.parse_args()
rec = json.loads(Path(a.recon).read_text())[0]
ref = rec["reference_lla"]; lat0, lon0 = ref["latitude"], ref["longitude"]
z = np.array([p["coordinates"][2] for p in rec["points"].values()]); zg = float(np.median(z))
cam = next(iter(rec["cameras"].values())); W, H = cam["width"], cam["height"]; S = max(W, H)
dets = json.loads(Path(a.dets).read_text()); dets.pop("__meta__", None)
out = []
for img, bs in dets.items():
    sh = rec["shots"].get(img)
    for b in bs:
        if b["conf"] < a.conf:
            continue
        if sh is None:
            out.append({"img": img, **b, "lat": None, "lon": None, "why": "photo not in ODM reconstruction"}); continue
        Rm, _ = cv2.Rodrigues(np.array(sh["rotation"])); t = np.array(sh["translation"]); C = -Rm.T @ t
        u, v = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
        xn = (u + 0.5 - W / 2) / S; yn = (v + 0.5 - H / 2) / S
        ray = Rm.T @ np.array([(xn - cam["c_x"]) / cam["focal_x"], (yn - cam["c_y"]) / cam["focal_y"], 1.0])
        if ray[2] >= 0:
            out.append({"img": img, **b, "lat": None, "lon": None, "why": "ray does not hit ground"}); continue
        s = (zg - C[2]) / ray[2]; P = C + s * ray
        lat = lat0 + math.degrees(P[1] / R_E); lon = lon0 + math.degrees(P[0] / (R_E * math.cos(math.radians(lat0))))
        out.append({"img": img, **{k: round(v_, 4) for k, v_ in b.items()}, "lat": lat, "lon": lon,
                    "e_topo": round(float(P[0]), 1), "n_topo": round(float(P[1]), 1), "agl_m": round(float(C[2] - zg), 1),
                    "offset_from_nadir_m": round(float(np.hypot(P[0] - C[0], P[1] - C[1])), 1)})
Path(a.out).write_text(json.dumps({"ground_z_m": zg, "ground_z_p5_p95": [float(np.percentile(z, 5)), float(np.percentile(z, 95))],
                                   "reference_lla": ref, "dets": out}, indent=1))
print(len(out), "dets georeferenced; ground z", round(zg, 1), "agl", sorted({d.get('agl_m') for d in out if d.get('agl_m')})[:3])
