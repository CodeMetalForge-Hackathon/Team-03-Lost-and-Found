"""Sonar mosaic forming along a boat/AUV track + detector call-outs. SIMULATED PLACEMENT, labelled as such.

Usage: mosaic.py [--pings 120] [--every_png 6]
Inputs
  track  : real ALICE-AUV navigation (Red Sea, Zenodo 10544811, session 2023-09-03-11-37-57; timestamp, lat, lon, yaw,
           depth), extracted from the remote zip by range requests. Translated (not rotated or scaled) so its centroid
           sits on the centroid of Hinckley Lake, the largest water body on the night COP grid. Poses that fall outside
           the OSM water mask are dropped.
  frames : UATD Test_2 forward-looking-sonar frames (held out from training), taken IN FILE ORDER (no picking),
           polar 1024 beams x N range bins, 120 deg azimuth, max range from each frame's XML. Row 0 = nearest bin (assumed).
Per ping: the polar frame is warped to a Cartesian fan at the pose and heading and max-accumulated into a 0.2 m/px
mosaic raster (log-stretched intensity). The YOLO11n UATD detector runs on the raw polar frame; each box centre
(beam, bin) -> (bearing, range) -> world position. A PNG is written every N pings.
Outputs: water/mosaic/{frames/mNNN.png, mosaic.json}
"""
import sys, json, math, csv, argparse, time
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np, cv2

Z = Path(__file__).resolve().parent.parent
NIGHT = Path.home() / "forge/night"
R_E = 6371008.8
MPP = 0.2
CLASSES = ["cube", "ball", "cylinder", "human body", "tyre", "circle cage", "square cage", "metal bucket", "plane", "rov"]


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--pings", type=int, default=120); ap.add_argument("--every_png", type=int, default=6)
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args(); t0 = time.time()
    out = Z / "water" / "mosaic"; (out / "frames").mkdir(parents=True, exist_ok=True)
    for p in (out / "frames").glob("*.png"): p.unlink()
    cfg = json.loads((NIGHT / "config.json").read_text()); lat0, lon0 = cfg["lkp"]["lat"], cfg["lkp"]["lon"]
    meta = json.loads((NIGHT / "map/features_meta.json").read_text()); F = np.load(NIGHT / "map/features.npz")
    N, CELL, HALF = meta["n"], meta["cell_m"], meta["half_m"]
    water = F["water"]
    from scipy import ndimage
    lab, n = ndimage.label(water <= 0); sz = ndimage.sum(np.ones_like(water), lab, range(1, n + 1)); k = int(np.argmax(sz)) + 1
    rr, cc = np.where(lab == k); lake_e = float((-HALF + (cc + .5) * CELL).mean()); lake_n = float((HALF - (rr + .5) * CELL).mean())
    cellE = lambda e: int((e + HALF) // CELL); cellN = lambda n_: int((HALF - n_) // CELL)
    # --- track
    nav = list(csv.DictReader(open(Z / "water/redsea_nav/2023-09-03-11-37-57_navigation.csv")))
    la = np.array([float(x["latitude"]) for x in nav]); lo = np.array([float(x["longitude"]) for x in nav])
    yaw = np.array([float(x["yaw"]) for x in nav]); ts = np.array([float(x["timestamp"]) for x in nav]); dep = np.array([float(x["depth"]) for x in nav])
    te = (lo - lo.mean()) * 111320 * math.cos(math.radians(la.mean())); tn = (la - la.mean()) * 110540
    # yaw convention: compare with direction of motion (smoothed) — pick NED heading (0=N, cw) or ENU (0=E, ccw)
    de, dn = np.gradient(cv2.GaussianBlur(te.reshape(-1, 1), (1, 61), 0).ravel()), np.gradient(cv2.GaussianBlur(tn.reshape(-1, 1), (1, 61), 0).ravel())
    mv = np.hypot(de, dn) > 0.02; mot = np.arctan2(de, dn)[mv]           # NED heading of motion
    err = lambda h: float(np.median(np.abs(np.angle(np.exp(1j * (h[mv] - mot))))))
    cands = {"ned": yaw, "enu": math.pi / 2 - yaw}
    conv = min(cands, key=lambda c: err(cands[c])); head = cands[conv]
    E = te + lake_e; Nn = tn + lake_n
    inwater = np.array([0 <= cellN(n_) < N and 0 <= cellE(e) < N and water[cellN(n_), cellE(e)] <= 10 for e, n_ in zip(E, Nn)])
    idx_ok = np.flatnonzero(inwater)
    step = max(1, len(idx_ok) // a.pings); pings = idx_ok[::step][:a.pings]
    # --- frames
    fdir = Z / "water/uatd/UATD_Test_2"
    frames = sorted((fdir / "images").glob("*.bmp"))[:len(pings)]
    from ultralytics import YOLO
    det = YOLO(str(Z / "water/uatd_yolo11n_best.pt"))
    # --- canvas over the track + fan margin
    m = 25.0
    e0, e1, n0, n1 = E[pings].min() - m, E[pings].max() + m, Nn[pings].min() - m, Nn[pings].max() + m
    Wc, Hc = int((e1 - e0) / MPP), int((n1 - n0) / MPP)
    acc = np.zeros((Hc, Wc), np.float32); cov = np.zeros((Hc, Wc), np.uint8)
    callouts, outframes, track = [], [], []; n_gt_h = 0
    en2ll = lambda e, n_: (lat0 + math.degrees(n_ / R_E), lon0 + math.degrees(e / (R_E * math.cos(math.radians(lat0)))))
    for k_, (pi, fp) in enumerate(zip(pings, frames)):
        x = ET.parse(fdir / "annotations" / (fp.stem + ".xml")).getroot()
        rng = float(x.find("sonar/range").text); az = math.radians(float(x.find("sonar/azimuth").text))
        pol = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE).astype(np.float32); Hp, Wp = pol.shape
        pol_s = np.log1p(pol) / math.log1p(255.0)                              # log stretch, 0..1
        # fan in local canvas pixels
        ce, cn = E[pi], Nn[pi]; h = head[pi]
        r_px = rng / MPP; cx, cy = (ce - e0) / MPP, (n1 - cn) / MPP
        x0, x1 = int(max(0, cx - r_px - 2)), int(min(Wc, cx + r_px + 2)); y0, y1 = int(max(0, cy - r_px - 2)), int(min(Hc, cy + r_px + 2))
        gx, gy = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
        dx, dy = (gx - cx) * MPP, (cy - gy) * MPP                             # east, north metres
        rho = np.hypot(dx, dy); brg = np.arctan2(dx, dy) - h                     # bearing relative to heading
        brg = (brg + math.pi) % (2 * math.pi) - math.pi
        inside = (rho <= rng) & (np.abs(brg) <= az / 2)
        mapx = ((brg + az / 2) / az * (Wp - 1)).astype(np.float32); mapy = (rho / rng * (Hp - 1)).astype(np.float32)
        samp = cv2.remap(pol_s, mapx, mapy, cv2.INTER_LINEAR)
        sub = acc[y0:y1, x0:x1]; np.maximum(sub, np.where(inside, samp, 0), out=sub); cov[y0:y1, x0:x1] |= inside.astype(np.uint8)
        la_, lo_ = en2ll(ce, cn); track.append({"lat": la_, "lon": lo_, "e": round(ce, 1), "n": round(cn, 1), "heading_deg": round(math.degrees(h) % 360, 1),
                                                "depth_m": round(float(dep[pi]), 1), "t": float(ts[pi]), "frame": fp.name, "range_m": rng})
        gts_h = [[float(o.find("bndbox").find(q).text) for q in ("xmin", "ymin", "xmax", "ymax")] for o in x.findall("object")
                 if o.find("name").text.strip() == "human body"]
        n_gt_h += len(gts_h)
        r = det.predict(str(fp), imgsz=640, conf=a.conf, verbose=False)[0]
        for b, c, s in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy()):
            u, v = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            bb = (u / (Wp - 1)) * az - az / 2; rr_ = v / (Hp - 1) * rng
            de_, dn_ = rr_ * math.sin(h + bb), rr_ * math.cos(h + bb)
            la2, lo2 = en2ll(ce + de_, cn + dn_)
            callouts.append({"ping": k_, "frame": fp.name, "cls": CLASSES[int(c)], "conf": round(float(s), 3), "lat": la2, "lon": lo2,
                             "e": round(ce + de_, 1), "n": round(cn + dn_, 1), "range_m": round(rr_, 1), "bearing_deg": round(math.degrees(bb), 1),
                             "pose_lat": la_, "pose_lon": lo_, "box_px": [round(float(q), 1) for q in b],
                             "matches_label": (int(c) == 3 and any(_iou(b, g) >= 0.5 for g in gts_h)) if int(c) == 3 else None})
        if (k_ + 1) % a.every_png == 0 or k_ == len(pings) - 1:
            img = cv2.applyColorMap((np.clip(acc, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_BONE)
            pts = np.array([[(t["e"] - e0) / MPP, (n1 - t["n"]) / MPP] for t in track], np.int32)
            cv2.polylines(img, [pts], False, (60, 200, 255), 2)
            for co in callouts:
                p = (int((co["e"] - e0) / MPP), int((n1 - co["n"]) / MPP))
                if co["cls"] == "human body": cv2.circle(img, p, 9, (60, 60, 255), 3)
                else: cv2.circle(img, p, 4, (150, 150, 150), 1)
            rgba = np.dstack([img, np.where(cov > 0, 255, 0).astype(np.uint8)])
            name = f"m{k_+1:03d}.png"; cv2.imwrite(str(out / "frames" / name), rgba)
            outframes.append({"png": name, "ping": k_ + 1, "n_callouts": len(callouts),
                              "n_human": sum(1 for c in callouts if c["cls"] == "human body")})
    sw, ne = en2ll(e0, n0), en2ll(e1, n1)
    nh = [c for c in callouts if c["cls"] == "human body"]
    info = {"label": "FLS frames placed along a real AUV track — SIMULATED placement",
            "track_source": "ALICE-AUV navigation, Red Sea (Eilat), session 2023-09-03 11:37:57, Zenodo 10544811 (CC BY 4.0); translated onto Hinckley Lake (Ohio) on the COP grid; heading convention " + conv,
            "frames_source": f"UATD Test_2 (CC BY 4.0), first {len(pings)} frames in file order; held out from training",
            "detector": "YOLO11n trained on UATD Training (water/RESULTS.md), conf ≥ %.2f" % a.conf,
            "n_pings": len(pings), "pose_step": int(step), "track_poses_in_water": int(inwater.sum()), "track_poses_total": len(nav),
            "mpp": MPP, "bounds": {"s": sw[0], "w": sw[1], "n": ne[0], "e": ne[1]}, "bounds_en": [e0, n0, e1, n1],
            "lake": {"e": lake_e, "n": lake_n, "cells": int(sz[k - 1])}, "frames": outframes, "interval_ms": 350,
            "track": track, "callouts": callouts, "n_callouts": len(callouts), "n_human": len(nh),
            "by_class": {c: sum(1 for x in callouts if x["cls"] == c) for c in CLASSES},
            "human_check": {"labelled_human_bodies_in_placed_frames": n_gt_h, "human_callouts": len(nh),
                            "match_label_iou50": sum(1 for c in nh if c["matches_label"]), "no_matching_label": sum(1 for c in nh if not c["matches_label"])}, "runtime_s": round(time.time() - t0, 1)}
    (out / "mosaic.json").write_text(json.dumps(info, indent=1, default=float))
    print(json.dumps({k: info[k] for k in ("n_pings", "pose_step", "track_poses_in_water", "track_poses_total", "n_callouts", "n_human", "by_class", "runtime_s")}), "conv", conv)


if __name__ == "__main__":
    main()
