"""Deterministic incremental stitch of a drone survey: the map forms frame by frame.

Usage: stitch_live.py <images_dir> <out_dir> [--every 4] [--scale 0.25] [--dets dets.json]

Method (no learning, no inpainting):
  1. Downscale each frame (default 0.25), SIFT features (all of them, at 0.5 scale; FLANN, ratio 0.8).
  2. Frame 0 is the reference plane. For frame i, take the already-placed frames nearest by EXIF GPS (up to 4),
     match SIFT (ratio 0.75), RANSAC homography i->j, compose H_i = H_j @ H_ij. Accept the first match with
     >= 40 inliers whose composed H is close to a similarity (scale within 0.6–1.6 of frame 0, small perspective).
     Frames with no acceptable match are skipped and counted.
  3. Warp each placed frame into a growing canvas in capture order; write a PNG every N frames.
  4. Georeference (approximate): least-squares similarity from canvas frame centres to EXIF GPS (local metres),
     report the RMS residual in metres. Also the 2-point (first/last placed frame) fit, as the prompt asks.
Outputs: out_dir/frames/fNNN.png, out_dir/final.png, out_dir/stitch.json.
"""
import sys, json, math, argparse, time
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ExifTags

R = 6371008.8


def exif_gps(p):
    e = Image.open(p)._getexif() or {}
    g = {ExifTags.GPSTAGS.get(k, k): v for k, v in e.get(34853, {}).items()}
    c = lambda v: float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
    lat = c(g["GPSLatitude"]) * (1 if g["GPSLatitudeRef"] == "N" else -1)
    lon = c(g["GPSLongitude"]) * (1 if g["GPSLongitudeRef"] == "E" else -1)
    return lat, lon, float(g.get("GPSAltitude", 0)), e.get(36867)


def sim_ok(H, s0):
    A = H[:2, :2]; s = math.sqrt(abs(np.linalg.det(A)))
    if not (0.6 * s0 < s < 1.6 * s0):
        return False
    if abs(H[2, 0]) > 2e-3 or abs(H[2, 1]) > 2e-3:
        return False
    sv = np.linalg.svd(A, compute_uv=False)
    return sv[0] / max(sv[1], 1e-9) < 1.5        # not too sheared


def fit_similarity(src, dst):
    """Least-squares similarity src(x,y)->dst(e,n): returns 2x3 matrix (Umeyama, reflection allowed for y-down)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    if M is None:
        return None
    return M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images"); ap.add_argument("out")
    ap.add_argument("--every", type=int, default=4); ap.add_argument("--scale", type=float, default=0.25)
    ap.add_argument("--feat_scale", type=float, default=0.5)
    ap.add_argument("--source", default="Aukerman Park ODM sample flight (OpenDroneMap odm_data_aukerman)")
    ap.add_argument("--dets", default=None); ap.add_argument("--max_side", type=int, default=1800)
    a = ap.parse_args()
    t0 = time.time()
    out = Path(a.out); (out / "frames").mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in Path(a.images).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    gps = [exif_gps(p) for p in files]
    lat0, lon0 = gps[0][0], gps[0][1]
    en = np.array([(math.radians(g[1] - lon0) * R * math.cos(math.radians(lat0)), math.radians(g[0] - lat0) * R) for g in gps])
    sift = cv2.SIFT_create(nfeatures=0)          # all features: grass/canopy texture needs them (4000 strongest failed)
    imgs, kps = [], []
    fs_ = a.feat_scale; r_ = a.scale / fs_      # features found at feat_scale, canvas rendered at scale
    for p in files:
        full = cv2.imread(str(p))
        imgs.append(cv2.resize(full, None, fx=a.scale, fy=a.scale, interpolation=cv2.INTER_AREA))
        g_ = cv2.cvtColor(cv2.resize(full, None, fx=fs_, fy=fs_, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        k, d = sift.detectAndCompute(g_, None)
        kps.append((np.float32([q.pt for q in k]) * r_, d))
    bf = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=64))
    H = [None] * len(files); H[0] = np.eye(3); s0 = 1.0
    link = [None] * len(files); inl = [0] * len(files)
    for i in range(1, len(files)):
        placed = [j for j in range(i) if H[j] is not None]
        order = sorted(placed, key=lambda j: np.hypot(*(en[i] - en[j])))[:4]
        for j in order:
            pi, di = kps[i]; pj, dj = kps[j]
            if di is None or dj is None or len(di) < 10 or len(dj) < 10:
                continue
            m = bf.knnMatch(di, dj, k=2)
            good = [x[0] for x in m if len(x) == 2 and x[0].distance < 0.8 * x[1].distance]
            if len(good) < 40:
                continue
            Hij, mask = cv2.findHomography(pi[[g.queryIdx for g in good]], pj[[g.trainIdx for g in good]], cv2.RANSAC, 4.0)
            if Hij is None or mask.sum() < 40:
                continue
            Hi = H[j] @ Hij; Hi /= Hi[2, 2]
            if sim_ok(Hi, s0):
                H[i], link[i], inl[i] = Hi, j, int(mask.sum()); break
    h, w = imgs[0].shape[:2]
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    allc = np.concatenate([cv2.perspectiveTransform(corners, H[i]) for i in range(len(files)) if H[i] is not None])
    x0, y0 = np.floor(allc.min(0)[0]); x1, y1 = np.ceil(allc.max(0)[0])
    T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], float)
    CW, CH = int(x1 - x0), int(y1 - y0)
    ds = min(1.0, a.max_side / max(CW, CH))
    canvas = np.zeros((CH, CW, 3), np.uint8); cmask = np.zeros((CH, CW), np.uint8)
    dets = json.loads(Path(a.dets).read_text()) if a.dets else {}
    frames, nplaced, ndet = [], 0, 0
    boxes_canvas = []
    centers_px, centers_en, placed_idx = [], [], []
    for i, p in enumerate(files):
        if H[i] is not None:
            M = T @ H[i]
            wm = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (CW, CH), flags=cv2.INTER_NEAREST)
            wm = cv2.erode(wm, np.ones((5, 5), np.uint8))
            wi = cv2.warpPerspective(imgs[i], M, (CW, CH))
            canvas[wm > 0] = wi[wm > 0]; cmask |= wm
            c = cv2.perspectiveTransform(np.float32([[[w / 2, h / 2]]]), M)[0, 0]
            centers_px.append(c); centers_en.append(en[i]); placed_idx.append(i); nplaced += 1
            for d in dets.get(p.name, []):                      # boxes in full-res pixels
                bx = np.float32([[[d["x0"] * a.scale, d["y0"] * a.scale]], [[d["x1"] * a.scale, d["y1"] * a.scale]]])
                q = cv2.perspectiveTransform(bx, M).reshape(-1, 2)
                boxes_canvas.append({"img": p.name, "conf": d["conf"], "x0": float(q[:, 0].min()), "y0": float(q[:, 1].min()),
                                     "x1": float(q[:, 0].max()), "y1": float(q[:, 1].max())}); ndet += 1
        if (i + 1) % a.every == 0 or i == len(files) - 1:
            view = canvas.copy()
            for b in boxes_canvas:
                cv2.rectangle(view, (int(b["x0"]) - 6, int(b["y0"]) - 6), (int(b["x1"]) + 6, int(b["y1"]) + 6), (80, 80, 255), 3)
            if H[i] is not None:
                q = cv2.perspectiveTransform(corners, T @ H[i]).astype(np.int32)
                cv2.polylines(view, [q], True, (255, 200, 60), 3)
            rgba = np.dstack([view, cmask])
            small = cv2.resize(rgba, None, fx=ds, fy=ds, interpolation=cv2.INTER_AREA)
            name = f"f{i+1:03d}.png"; cv2.imwrite(str(out / "frames" / name), small)
            frames.append({"png": name, "n": i + 1, "placed": nplaced, "dets": ndet if a.dets else None})
    cv2.imwrite(str(out / "final.png"), np.dstack([canvas, cmask]))
    cv2.imwrite(str(out / "final_small.png"), cv2.resize(np.dstack([canvas, cmask]), None, fx=ds, fy=ds, interpolation=cv2.INTER_AREA))
    # georeference: canvas px -> local metres (east, north) from frame 0's GPS
    cp, ce = np.float32(centers_px), np.float32(centers_en)
    F = np.float32([[1, 0], [0, -1]])            # image y grows south: flip before a rotation+scale+shift fit
    Mf = fit_similarity(cp @ F, ce)
    Mls = np.hstack([Mf[:, :2] @ F, Mf[:, 2:]])  # so that en = Mls @ [x, y, 1]
    res = np.hypot(*(cp @ Mls[:, :2].T + Mls[:, 2] - ce).T)
    # 2-point fit from first and last placed frame
    a_, b_ = cp[0], cp[-1]; A_, B_ = ce[0], ce[-1]
    zc = complex(*(b_ - a_)); Zc = complex(*(B_ - A_)); k = Zc / zc
    # y-down image vs north-up: use conjugate mapping (reflection) since image y grows south
    zc2 = complex(b_[0] - a_[0], -(b_[1] - a_[1])); k2 = Zc / zc2
    pred2 = np.array([[(k2 * complex(p[0] - a_[0], -(p[1] - a_[1]))).real + A_[0], (k2 * complex(p[0] - a_[0], -(p[1] - a_[1]))).imag + A_[1]] for p in cp])
    res2 = np.hypot(*(pred2 - ce).T)
    def px2ll(x, y):
        e_, n_ = Mls @ np.array([x, y, 1.0])
        return lat0 + math.degrees(n_ / R), lon0 + math.degrees(e_ / (R * math.cos(math.radians(lat0))))
    corners_ll = [px2ll(0, 0), px2ll(CW, 0), px2ll(CW, CH), px2ll(0, CH)]
    mpp = math.sqrt(abs(np.linalg.det(Mls[:, :2])))
    boxes_ll = []
    for b in boxes_canvas:
        la, lo = px2ll((b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2)
        boxes_ll.append({**b, "lat": la, "lon": lo})
    info = {"source": f"{a.source} ({len(files)} photos, {gps[0][3]} → {gps[-1][3]})",
            "method": f"SIFT + RANSAC homography to the nearest already-placed frame (by EXIF GPS), chained to frame 1; warped into a growing canvas. {nplaced}/{len(files)} frames placed; deterministic, no learned model, no inpainting.",
            "georef_note": (f"Georeference is APPROXIMATE: least-squares similarity from {nplaced} frame centres to their EXIF GPS, RMS residual {float(np.sqrt((res**2).mean())):.1f} m "
                            f"(2-point first/last fit: RMS {float(np.sqrt((res2**2).mean())):.1f} m). Consumer GPS + homography drift; not a survey. "
                            "The ODM Aukerman orthophoto on :8143 is the fully rectified comparison."),
            "n_images": len(files), "n_placed": nplaced, "skipped": [files[i].name for i in range(len(files)) if H[i] is None],
            "frames": frames, "interval_ms": 450, "canvas_px": [CW, CH], "display_scale": ds, "m_per_canvas_px": mpp,
            "corners_ll": corners_ll, "rms_m_lsq": float(np.sqrt((res ** 2).mean())), "rms_m_2pt": float(np.sqrt((res2 ** 2).mean())),
            "affine_px_to_en": Mls.tolist(), "origin_ll": [lat0, lon0], "boxes": boxes_ll,
            "links": {files[i].name: (files[link[i]].name if link[i] is not None else None) for i in range(len(files))},
            "inliers": {files[i].name: inl[i] for i in range(len(files))}, "runtime_s": round(time.time() - t0, 1)}
    (out / "stitch.json").write_text(json.dumps(info, indent=1))
    print(json.dumps({k: info[k] for k in ("n_images", "n_placed", "canvas_px", "m_per_canvas_px", "rms_m_lsq", "rms_m_2pt", "runtime_s")}))


if __name__ == "__main__":
    main()
