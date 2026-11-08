"""Generate a SYNTHETIC dog-stand-in run in the exact DOG_HANDOFF folder format, so the whole
pipeline (track -> sync -> layers -> replay) is demoable before real runs arrive.

  python make_synthetic_run.py [--out night/data/dog/run_00_synthetic] [--seconds 150]

Writes sensors.csv, events.csv, overhead.mp4 (30 fps, with an audio track carrying the clap),
floor.txt, and SYNTHETIC.json (ground truth + the hidden clock offset, so tests can check sync).
Every screen that shows this run labels it SYNTHETIC.
"""
from __future__ import annotations
import argparse, json, math, subprocess, sys
from pathlib import Path
import numpy as np
import cv2
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vendor"))
import imageio_ffmpeg  # noqa: E402

FPS = 30
W, H = 1280, 720
FLOOR_W, FLOOR_H = 6.0, 4.0                       # metres between tape markers
MARKERS_M = [(0, 0), (FLOOR_W, 0), (FLOOR_W, FLOOR_H), (0, FLOOR_H)]
MARKERS_PX = [(300, 120), (980, 110), (1080, 640), (200, 650)]   # true camera projection (hidden)
WALLS = (-0.6, -0.6, FLOOR_W + 0.6, FLOOR_H + 0.6)
BOXES = [(4.6, 2.9, 5.4, 3.5), (1.6, 1.4, 2.2, 1.9)]           # x0,y0,x1,y1 metres
PERSON = (5.3, 3.85)                                           # hidden behind box 1, knocks
TOP_PPM = 80                                                   # top-down render scale
TOP_ORIGIN = (-1.0, -1.0)
TOP_SIZE = (int(8.0 * TOP_PPM), int(6.0 * TOP_PPM))


def m2top(x, y):
    return (int((x - TOP_ORIGIN[0]) * TOP_PPM), int((y - TOP_ORIGIN[1]) * TOP_PPM))


def build_path(rng, seconds):
    """Waypoints with speed, stops and a spin. Returns arrays at FPS: t, x, y, heading(rad), state."""
    wps = [(0.6, 0.6), (5.4, 0.6), (5.4, 1.3), (0.6, 1.3), (0.6, 2.1), (3.9, 2.1),
           (3.9, 3.0), (0.6, 3.0), (0.6, 3.6), (4.2, 3.7), (4.3, 3.8)]
    speed = 0.35
    pre = 13.0   # clap at 3 s, then 10 s still
    t, xs, ys, hs, st = [], [], [], [], []
    x, y = wps[0]; h = 0.0; clock = 0.0
    dt = 1 / FPS

    def push(state):
        nonlocal clock
        t.append(clock); xs.append(x); ys.append(y); hs.append(h); st.append(state); clock += dt

    while clock < pre:
        push("still")
    stops = {2: 3.0, 5: 3.0, 10: 4.0}
    spin_at = 7
    for i, (tx, ty) in enumerate(wps[1:], start=1):
        target_h = math.atan2(ty - y, tx - x)
        # turn in place first
        while abs((target_h - h + math.pi) % (2 * math.pi) - math.pi) > 0.05:
            dh = (target_h - h + math.pi) % (2 * math.pi) - math.pi
            h += np.sign(dh) * min(abs(dh), math.radians(120) * dt)
            push("turn")
        while math.hypot(tx - x, ty - y) > speed * dt:
            h = math.atan2(ty - y, tx - x)            # re-aim each step so drift can't miss the waypoint
            x += speed * dt * math.cos(h) + rng.normal(0, 0.002)
            y += speed * dt * math.sin(h) + rng.normal(0, 0.002)
            push("move")
        if i == spin_at:
            for _ in range(int(2.5 * FPS)):
                h += 2 * math.pi / (2.5 * FPS); push("spin")
        if i in stops:
            for _ in range(int(stops[i] * FPS)):
                push("stop")
    while clock < seconds:
        push("stop" if clock < seconds - 2 else "still")
    return (np.array(t), np.array(xs), np.array(ys), np.array(hs), st)


def raycast(x, y, h, max_m=4.0):
    """Distance from (x, y) along heading h to the first wall or box (metres) or None."""
    best = None
    dx, dy = math.cos(h), math.sin(h)
    segs = []
    x0, y0, x1, y1 = WALLS
    segs += [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    for bx0, by0, bx1, by1 in BOXES:
        segs += [((bx0, by0), (bx1, by0)), ((bx1, by0), (bx1, by1)), ((bx1, by1), (bx0, by1)), ((bx0, by1), (bx0, by0))]
    for (ax, ay), (bx, by) in segs:
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        tt = ((ax - x) * ey - (ay - y) * ex) / den
        uu = ((ax - x) * dy - (ay - y) * dx) / den
        if tt > 0.02 and 0 <= uu <= 1 and (best is None or tt < best):
            best = tt
    return best if best is not None and best <= max_m else None


def render_floor():
    img = np.full((TOP_SIZE[1], TOP_SIZE[0], 3), (92, 98, 104), np.uint8)
    x0, y0, x1, y1 = WALLS
    cv2.rectangle(img, m2top(-1, -1), m2top(x0, 5), (50, 50, 55), -1)
    cv2.rectangle(img, m2top(x1, -1), m2top(7, 5), (50, 50, 55), -1)
    cv2.rectangle(img, m2top(-1, -1), m2top(7, y0), (50, 50, 55), -1)
    cv2.rectangle(img, m2top(-1, y1), m2top(7, 5), (50, 50, 55), -1)
    for bx0, by0, bx1, by1 in BOXES:
        cv2.rectangle(img, m2top(bx0, by0), m2top(bx1, by1), (60, 120, 170), -1)
        cv2.rectangle(img, m2top(bx0, by0), m2top(bx1, by1), (40, 80, 120), 2)
    cv2.circle(img, m2top(*PERSON), int(0.18 * TOP_PPM), (40, 40, 60), -1)   # person (not tracked)
    for (mx, my) in MARKERS_M:                                                 # green tape X
        c = m2top(mx, my); r = int(0.15 * TOP_PPM)
        cv2.line(img, (c[0] - r, c[1] - r), (c[0] + r, c[1] + r), (60, 230, 60), 7)
        cv2.line(img, (c[0] - r, c[1] + r), (c[0] + r, c[1] - r), (60, 230, 60), 7)
    return img


def top_to_cam():
    src = np.float32([m2top(*m) for m in MARKERS_M])
    dst = np.float32(MARKERS_PX)
    return cv2.getPerspectiveTransform(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "data/dog/run_00_synthetic"))
    ap.add_argument("--seconds", type=float, default=150)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed)

    t, xs, ys, hs, st = build_path(rng, a.seconds)
    n = len(t)
    clap_v = 3.0
    board_offset_ms = 8417 + int(rng.integers(0, 3000))   # board t_ms at video t=0 (hidden truth)
    knocks_v = [40.0, 60.0, 80.0, 100.0, 120.0]
    run_start_v, run_end_v = 13.0, a.seconds - 1.0

    # ---- sensors at 50 Hz on the board clock ----
    ts = np.arange(0, a.seconds, 1 / 50)
    xi, yi = np.interp(ts, t, xs), np.interp(ts, t, ys)
    hu = np.unwrap(hs); hi = np.interp(ts, t, hu)
    stv = np.array(st)
    idx = np.clip((ts * FPS).astype(int), 0, n - 1)
    state = stv[idx]
    yaw_rate = np.gradient(hi, ts)                        # rad/s
    speed = np.hypot(np.gradient(xi, ts), np.gradient(yi, ts))
    acc_fwd = np.gradient(speed, ts) / 9.81
    moving = np.isin(state, ["move", "turn", "spin"])
    vib = np.where(moving, 0.05, 0.004)
    ax = acc_fwd + rng.normal(0, 1, ts.size) * vib
    ay = (speed * yaw_rate) / 9.81 + rng.normal(0, 1, ts.size) * vib
    az = 1.0 + rng.normal(0, 1, ts.size) * vib
    gx = rng.normal(0, 0.6, ts.size); gy = rng.normal(0, 0.6, ts.size)
    gz = np.degrees(yaw_rate) + rng.normal(0, 0.8, ts.size)
    sound = 110 + rng.normal(0, 6, ts.size) + np.where(moving, 70, 0)
    jolt = np.abs(ts - (clap_v + 0.012)) < 0.03
    ax[jolt] += 1.6; az[jolt] += 0.9
    sound[np.abs(ts - clap_v) < 0.04] += 820
    for k in knocks_v:
        for j in range(3):                               # knock-knock-knock, quieter (far away)
            sound[np.abs(ts - (k + j * 0.25)) < 0.03] += 260
    us = []
    for x, y, h in zip(xi, yi, hi):
        d = raycast(x, y, h)
        us.append(-1 if d is None else round(d * 100 + rng.normal(0, 1.5), 1))
    batt = np.round(7.9 - 0.0025 * ts + rng.normal(0, 0.005, ts.size), 3)
    t_ms = np.round(ts * 1000 + board_offset_ms).astype(int)
    with open(out / "sensors.csv", "w") as f:
        f.write("t_ms,ax,ay,az,gx,gy,gz,us_cm,us_angle_deg,sound,battery_v\n")
        for i in range(ts.size):
            f.write(f"{t_ms[i]},{ax[i]:.4f},{ay[i]:.4f},{az[i]:.4f},{gx[i]:.2f},{gy[i]:.2f},{gz[i]:.2f},"
                    f"{us[i]},0,{int(sound[i])},{batt[i]}\n")

    # ---- events typed by a human (board clock, with typing lag) ----
    def bt(v):
        return int(v * 1000 + board_offset_ms + rng.normal(250, 80))
    ev = [(bt(clap_v), "sync_clap", ""), (bt(run_start_v), "run_start", "")]
    prev = None
    for i in range(n):
        s = st[i]
        if s != prev and s in ("stop", "spin") and run_start_v < t[i] < run_end_v:
            ev.append((bt(t[i]), "dog_stop" if s == "stop" else "dog_spin", ""))
        prev = s
    ev.append((bt(knocks_v[0] - 1), "human_hidden", "behind box NE corner"))
    for k in knocks_v:
        ev.append((bt(k), "knock", "hidden person"))
    ev.append((bt(run_end_v), "run_end", ""))
    ev.sort()
    with open(out / "events.csv", "w") as f:
        f.write("t_ms,label,note\n")
        for tm, lab, note in ev:
            f.write(f"{tm},{lab},{note}\n")

    # ---- floor.txt ----
    (out / "floor.txt").write_text(
        "# SYNTHETIC run. Four floor markers (green tape X), measured positions in metres.\n"
        "# Convention: M1 is the marker nearest the image top-left; go clockwise in the image.\n"
        + "".join(f"M{i+1} {mx:.2f} {my:.2f}\n" for i, (mx, my) in enumerate(MARKERS_M))
        + "tape_color green\nmarker_color orange\n"
        + "".join(f"obstacle box {b[0]} {b[1]} {b[2]} {b[3]}\n" for b in BOXES)
        + f"person hidden {PERSON[0]} {PERSON[1]}\n")

    # ---- audio track for the video: room tone + clap + knocks + motor ----
    afs = 16000
    ta = np.arange(int(a.seconds * afs)) / afs
    audio = 0.01 * rng.standard_normal(ta.size)
    audio += 0.02 * np.interp(ta, ts, moving.astype(float)) * np.sin(2 * np.pi * 180 * ta)
    def burst(t0, amp, f0, dec):
        i = int(t0 * afs); m = int(0.2 * afs); tt = np.arange(m) / afs
        audio[i:i + m] += amp * np.exp(-tt / dec) * (rng.standard_normal(m) * 0.6 + np.sin(2 * np.pi * f0 * tt))
    burst(clap_v, 0.9, 2000, 0.015)
    for k in knocks_v:
        for j in range(3):
            burst(k + j * 0.25, 0.25, 300, 0.03)
    audio = np.clip(audio, -1, 1)
    wav = out / "_audio.wav"; sf.write(wav, audio, afs)

    # ---- video ----
    floor = render_floor()
    Hc = top_to_cam()
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out / "overhead.mp4")]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        top = floor.copy()
        c = m2top(xs[i], ys[i])
        cv2.circle(top, c, int(0.16 * TOP_PPM), (35, 35, 35), -1)            # rover body
        cv2.circle(top, c, int(0.09 * TOP_PPM), (0, 120, 255), -1)           # orange marker
        if abs(t[i] - clap_v) < 0.1:
            cv2.circle(top, m2top(xs[i] + 0.3, ys[i] + 0.2), int(0.1 * TOP_PPM), (150, 180, 230), -1)  # hands
        frame = cv2.warpPerspective(top, Hc, (W, H), borderValue=(30, 30, 30))
        frame = cv2.add(frame, rng.integers(0, 8, frame.shape, dtype=np.uint8))
        cv2.putText(frame, "SYNTHETIC", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        p.stdin.write(frame.tobytes())
    p.stdin.close(); p.wait()
    wav.unlink()

    truth = {"synthetic": True, "board_offset_ms": board_offset_ms, "clap_video_s": clap_v,
             "markers_px_true": MARKERS_PX, "boxes": BOXES, "person": PERSON,
             "knocks_video_s": knocks_v, "seconds": a.seconds, "seed": a.seed,
             "track_truth_csv": "truth_track.csv"}
    (out / "SYNTHETIC.json").write_text(json.dumps(truth, indent=1))
    np.savetxt(out / "truth_track.csv", np.c_[t, xs, ys, hs], delimiter=",",
               header="t_video_s,x_m,y_m,heading_rad", comments="", fmt="%.4f")
    print("wrote", out, "frames", n, "sensor rows", ts.size)


if __name__ == "__main__":
    main()
