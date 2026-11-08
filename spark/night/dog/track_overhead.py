"""Overhead video + floor.txt -> dog XY in metres at video frame rate.

1. Floor markers: pixel positions from `px M1 x y` lines in floor.txt if present, otherwise
   auto-detected as the four largest blobs of `tape_color` (HSV) in the first frames, ordered
   M1 = nearest image top-left, then clockwise in the image. Written to floor_px.json with a
   debug image (floor_check.png) so a human can verify before trusting the track.
2. Homography pixels -> metres from the four correspondences (cv2.findHomography).
3. Per frame: HSV threshold for `marker_color` -> largest blob near the last position -> centroid.
   Fallback: MOG2 background subtraction (largest moving blob). Short gaps (< 0.5 s) interpolated.

  python track_overhead.py RUN_DIR [--marker-hsv h0,s0,v0,h1,s1,v1] [--show]
Output: RUN_DIR/track.csv  (frame,t_video_s,px,py,x_m,y_m,method)
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import cv2

HSV = {   # OpenCV hue 0-179
    "orange": ((5, 120, 120), (22, 255, 255)),
    "green": ((40, 90, 90), (85, 255, 255)),
    "pink": ((150, 80, 120), (175, 255, 255)),
    "yellow": ((22, 100, 120), (35, 255, 255)),
    "blue": ((95, 120, 80), (125, 255, 255)),
}


def parse_floor(path: Path):
    marks, px, opts = {}, {}, {}
    for line in path.read_text().splitlines():
        s = line.split("#")[0].split()
        if not s:
            continue
        if s[0].upper().startswith("M") and len(s) == 3:
            marks[s[0].upper()] = (float(s[1]), float(s[2]))
        elif s[0] == "px" and len(s) == 4:
            px[s[1].upper()] = (float(s[2]), float(s[3]))
        elif len(s) == 2:
            opts[s[0]] = s[1]
    if len(marks) != 4:
        raise SystemExit(f"floor.txt needs exactly four 'M<n> x_m y_m' lines, found {len(marks)}")
    return dict(sorted(marks.items())), px, opts


def mask_hsv(frame, rng):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array(rng[0]), np.array(rng[1]))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def autodetect_markers(frames, color):
    acc = None
    for f in frames:
        m = mask_hsv(f, HSV[color]).astype(np.float32)
        acc = m if acc is None else acc + m
    m = (acc / len(frames) > 127).astype(np.uint8) * 255
    m = cv2.dilate(m, np.ones((5, 5), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m)
    order = np.argsort(stats[1:, cv2.CC_STAT_AREA])[::-1][:4] + 1
    if len(order) < 4:
        raise SystemExit(f"auto-detect found {len(order)} '{color}' tape blobs; add 'px M1 x y' lines to floor.txt")
    pts = cent[order]
    c = pts.mean(0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])      # image coords: clockwise = increasing angle
    pts = pts[np.argsort(ang)]
    start = int(np.argmin(pts[:, 0] + pts[:, 1]))             # nearest top-left
    pts = np.roll(pts, -start, axis=0)
    return [tuple(map(float, p)) for p in pts]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--marker-hsv")
    ap.add_argument("--max-jump-m", type=float, default=0.6, help="per-frame jump rejected above this")
    a = ap.parse_args()
    run = Path(a.run)
    marks, px, opts = parse_floor(run / "floor.txt")
    cap = cv2.VideoCapture(str(run / "overhead.mp4"))
    if not cap.isOpened():
        raise SystemExit("cannot open overhead.mp4")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    first = []
    for _ in range(10):
        ok, f = cap.read()
        if ok:
            first.append(f)
    if len(px) == 4:
        pix = [px[k] for k in marks]
        src = "floor.txt px lines"
    else:
        pix = autodetect_markers(first, opts.get("tape_color", "green"))
        src = f"auto-detected {opts.get('tape_color', 'green')} tape"
    Hm, _ = cv2.findHomography(np.float32(pix), np.float32(list(marks.values())))
    # reprojection check (exact with 4 points; reported so a 5th+ marker would show error)
    dbg = first[0].copy()
    for (k, (mx, my)), (u, v) in zip(marks.items(), pix):
        cv2.circle(dbg, (int(u), int(v)), 10, (0, 0, 255), 2)
        cv2.putText(dbg, f"{k} ({mx:g},{my:g})", (int(u) + 12, int(v)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.imwrite(str(run / "floor_check.png"), dbg)
    (run / "floor_px.json").write_text(json.dumps({"source": src, "px": dict(zip(marks, pix)),
                                                   "H_px_to_m": Hm.tolist()}, indent=1))

    rng = HSV[opts.get("marker_color", "orange")]
    if a.marker_hsv:
        v = [int(x) for x in a.marker_hsv.split(",")]; rng = (tuple(v[:3]), tuple(v[3:]))
    # static mask: marker-coloured pixels present in >60 % of 40 frames sampled across the video
    # (boxes, tape, furniture). The dog's marker moves, so it never survives this vote.
    nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    votes = None; ns = 0
    for fi in np.linspace(0, max(0, nfr - 1), 40).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(fi)); ok, f = cap.read()
        if not ok:
            continue
        mm = (mask_hsv(f, rng) > 0).astype(np.float32)
        votes = mm if votes is None else votes + mm; ns += 1
    static = cv2.dilate(((votes / max(ns, 1)) > 0.6).astype(np.uint8), np.ones((9, 9), np.uint8)) if votes is not None else None
    bg = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=32, detectShadows=False)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    rows = []; last = None; i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        fg = bg.apply(f)
        m = mask_hsv(f, rng)
        if static is not None:
            m[static > 0] = 0
        n, lab, stats, cent = cv2.connectedComponentsWithStats(m)
        cand = [(stats[j, cv2.CC_STAT_AREA], cent[j]) for j in range(1, n) if stats[j, cv2.CC_STAT_AREA] >= 12]
        pt, method = None, ""
        if cand:
            if last is not None:
                cand.sort(key=lambda c: np.hypot(*(c[1] - last)))
                pt = cand[0][1]
            else:
                pt = max(cand, key=lambda c: c[0])[1]
            method = "hsv"
        else:
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            n2, _, st2, ce2 = cv2.connectedComponentsWithStats(fg)
            if n2 > 1:
                j = 1 + int(np.argmax(st2[1:, cv2.CC_STAT_AREA]))
                if st2[j, cv2.CC_STAT_AREA] > 80:
                    pt, method = ce2[j], "bgsub"
        if pt is not None:
            xy = cv2.perspectiveTransform(np.float32([[pt]]), Hm)[0, 0]
            if rows and rows[-1][4] == rows[-1][4] and math.hypot(xy[0] - rows[-1][4], xy[1] - rows[-1][5]) > a.max_jump_m:
                pt, method = None, ""
        if pt is not None:
            last = np.array(pt)
            rows.append([i, i / fps, float(pt[0]), float(pt[1]), float(xy[0]), float(xy[1]), method])
        else:
            rows.append([i, i / fps, np.nan, np.nan, np.nan, np.nan, "none"])
        i += 1
    arr = np.array([r[:6] for r in rows], float)
    meth = [r[6] for r in rows]
    good = ~np.isnan(arr[:, 4])
    # interpolate gaps shorter than 0.5 s
    if good.sum() >= 2:
        gi = np.where(~good)[0]
        gidx = np.where(good)[0]
        for k in gi:
            prev = gidx[gidx < k]; nxt = gidx[gidx > k]
            if len(prev) and len(nxt) and (nxt[0] - prev[-1]) / fps < 0.5:
                w = (k - prev[-1]) / (nxt[0] - prev[-1])
                arr[k, 2:6] = arr[prev[-1], 2:6] * (1 - w) + arr[nxt[0], 2:6] * w
                meth[k] = "interp"
    with open(run / "track.csv", "w") as fo:
        fo.write("frame,t_video_s,px,py,x_m,y_m,method\n")
        for r, mth in zip(arr, meth):
            fo.write(f"{int(r[0])},{r[1]:.4f},{r[2]:.1f},{r[3]:.1f},{r[4]:.4f},{r[5]:.4f},{mth}\n")
    counts = {k: meth.count(k) for k in set(meth)}
    summary = {"frames": len(rows), "fps": fps, "markers": src, "methods": counts}
    truth = run / "truth_track.csv"
    if truth.exists():
        tr = np.loadtxt(truth, delimiter=",", skiprows=1)
        nn = min(len(tr), len(arr)); ok = ~np.isnan(arr[:nn, 4])
        err = np.hypot(arr[:nn, 4] - tr[:nn, 1], arr[:nn, 5] - tr[:nn, 2])[ok]
        summary["vs_synthetic_truth_m"] = {"median": round(float(np.median(err)), 4),
                                           "p95": round(float(np.percentile(err, 95)), 4)}
    (run / "track_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
