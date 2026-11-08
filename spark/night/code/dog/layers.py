"""Track + sensors + events (aligned by sync.json) -> time-stamped layers for replay and fusion.

Layers (all times on the board clock t_ms; positions in floor metres):
  coverage   0.5 m grid. Every track sample adds dwell to cells whose centre is within the sweep
             radius R of the dog. POD(cell) = 1 - exp(-dwell / TAU). R = 0.75 m, TAU = 1.5 s are an
             ILLUSTRATIVE detection model for a rover-borne sensor, not a measured dog POD.
             Snapshots every 0.5 s for the replay scrubber.
  alerts     auto: dog_stop (track speed < 0.05 m/s for >= 2 s during the run), dog_spin
             (|integrated gz| >= 300 deg within 3 s), sound_spike (sound > median + 8 MAD,
             outside the sync clap); labeled: every events.csv row except sync/run markers.
             Each alert gets the dog's interpolated position at its time.
  occupancy  ultrasonic hit points: dog position + (us_cm/100) along heading (+ us_angle_deg);
             heading from the track's direction of travel, integrated gyro while turning in place.
             Also a 0.25 m log-odds grid (endpoint occupied, ray free).

  python layers.py RUN_DIR [--emit] [--origin-epoch S]
Output: RUN_DIR/layers.json.  --emit also writes alerts to night/inbox/ (sensor "dog1").
"""
from __future__ import annotations
import argparse, json, math, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "fusion"))
from sync import load_sensors, load_events  # noqa: E402
from track_overhead import parse_floor  # noqa: E402

CELL = 0.5
R_SWEEP = 0.75
TAU = 1.5
SNAP_S = 0.5
OCC_CELL = 0.25
LABEL_SKIP = {"sync_clap", "run_start", "run_end"}
ALERT_CONF = {"dog_alert": 0.6, "dog_bark": 0.5, "dog_stop": 0.3, "dog_spin": 0.35, "sound_spike": 0.3,
              "knock": 0.5, "shout": 0.6, "tap3": 0.7, "human_still": 0.0, "human_moving": 0.0,
              "human_hidden": 0.0, "obstacle": 0.0, "other": 0.1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--origin-epoch", type=float, help="wall-clock epoch for board t_ms of run_start (emit)")
    a = ap.parse_args()
    run = Path(a.run)
    marks, _, opts = parse_floor(run / "floor.txt")
    sync = json.loads((run / "sync.json").read_text())
    off = sync["offset_ms"]
    tr = np.genfromtxt(run / "track.csv", delimiter=",", names=True, dtype=None, encoding=None)
    tt = tr["t_video_s"] * 1000 + off
    ok = ~np.isnan(tr["x_m"])
    tt, tx, ty = tt[ok], tr["x_m"][ok], tr["y_m"][ok]
    s = load_sensors(run)
    ev = load_events(run)
    ts = s["t_ms"]
    t_start = next((e["t_ms"] for e in ev if e["label"] == "run_start"), tt[0])
    t_end = next((e["t_ms"] for e in ev if e["label"] == "run_end"), tt[-1])
    t_clap = (sync["board_clap_sound_ms"] + sync["board_clap_imu_ms"]) / 2

    def pos_at(t):
        return float(np.interp(t, tt, tx)), float(np.interp(t, tt, ty))

    # floor extent from markers + 0.5 m margin
    mx = np.array(list(marks.values()))
    x0, y0 = mx.min(0) - 0.5; x1, y1 = mx.max(0) + 0.5
    nx, ny = int(math.ceil((x1 - x0) / CELL)), int(math.ceil((y1 - y0) / CELL))
    cx = x0 + (np.arange(nx) + 0.5) * CELL; cy = y0 + (np.arange(ny) + 0.5) * CELL
    CX, CY = np.meshgrid(cx, cy)

    # ---- coverage (only during the run) ----
    dwell = np.zeros((ny, nx))
    snaps = []
    next_snap = t_start
    dt_tr = np.diff(tt, prepend=tt[0]) / 1000
    for k in range(len(tt)):
        if tt[k] < t_start or tt[k] > t_end:
            continue
        d = np.hypot(CX - tx[k], CY - ty[k]) <= R_SWEEP
        dwell[d] += dt_tr[k]
        if tt[k] >= next_snap:
            snaps.append({"t_ms": int(tt[k]), "pod": np.round(1 - np.exp(-dwell / TAU), 3).tolist()})
            next_snap += SNAP_S * 1000
    pod = 1 - np.exp(-dwell / TAU)
    snaps.append({"t_ms": int(t_end), "pod": np.round(pod, 3).tolist()})

    # ---- auto alerts ----
    alerts = []
    in_run = lambda t: t_start <= t <= t_end  # noqa: E731
    vt = np.hypot(np.gradient(tx, tt / 1000), np.gradient(ty, tt / 1000))
    vt = np.convolve(vt, np.ones(9) / 9, "same")
    still = (vt < 0.05) & (tt >= t_start) & (tt <= t_end)
    k = 0
    while k < len(tt):
        if still[k]:
            j = k
            while j < len(tt) and still[j]:
                j += 1
            if (tt[j - 1] - tt[k]) >= 2000:
                x, y = pos_at(tt[k])
                alerts.append({"t_ms": int(tt[k]), "kind": "dog_stop", "source": "auto:track",
                               "x": x, "y": y, "dur_s": round((tt[j - 1] - tt[k]) / 1000, 1)})
            k = j
        else:
            k += 1
    gz = s["gz"]; dts = np.diff(ts, prepend=ts[0]) / 1000
    yaw = np.cumsum(gz * dts)
    last_spin = -1e18
    for i in range(len(ts)):
        if not in_run(ts[i]) or ts[i] - last_spin < 3000:
            continue
        j = np.searchsorted(ts, ts[i] + 3000)
        if j < len(ts) and abs(yaw[j] - yaw[i]) >= 300:
            x, y = pos_at(ts[i])
            alerts.append({"t_ms": int(ts[i]), "kind": "dog_spin", "source": "auto:gyro", "x": x, "y": y,
                           "deg": round(float(yaw[j] - yaw[i]))})
            last_spin = ts[i]
    snd = s["sound"].astype(float)
    # rolling 5 s median / MAD: the motor raises the floor while moving, a global threshold misses knocks
    from scipy.ndimage import median_filter
    wn = max(5, int(5000 / np.median(np.diff(ts))) | 1)
    med = median_filter(snd, wn, mode="nearest")
    mad = median_filter(np.abs(snd - med), wn, mode="nearest") + 2.0
    spike = snd > med + 8 * mad
    last = -1e18
    for i in np.where(spike)[0]:
        if abs(ts[i] - t_clap) < 1000 or ts[i] - last < 1000:
            continue
        x, y = pos_at(ts[i])
        alerts.append({"t_ms": int(ts[i]), "kind": "sound_spike", "source": "auto:sound", "x": x, "y": y,
                       "level": int(snd[i]), "thr": round(float(med[i] + 8 * mad[i]))})
        last = ts[i]
    # labeled
    for e in ev:
        if e["label"] in LABEL_SKIP:
            continue
        x, y = pos_at(e["t_ms"])
        alerts.append({"t_ms": e["t_ms"], "kind": e["label"], "source": "labeled", "x": x, "y": y,
                       "note": e["note"]})
    for al in alerts:
        al["confidence"] = ALERT_CONF.get(al["kind"], 0.1)
        al["x"], al["y"] = round(al["x"], 3), round(al["y"], 3)
    alerts.sort(key=lambda r: r["t_ms"])

    # ---- ultrasonic occupancy ----
    kk = 9   # 0.3 s moving average at 30 fps before differentiating
    sx = np.convolve(np.pad(tx, kk // 2, mode="edge"), np.ones(kk) / kk, "valid")
    sy = np.convolve(np.pad(ty, kk // 2, mode="edge"), np.ones(kk) / kk, "valid")
    hx = np.interp(ts, tt, sx); hy = np.interp(ts, tt, sy)
    # heading: direction of travel where moving; integrated gyro (deg) where turning in place
    vx = np.gradient(hx, ts / 1000); vy = np.gradient(hy, ts / 1000)
    sp = np.hypot(vx, vy)
    head = np.zeros(len(ts)); cur = None
    for i in range(len(ts)):
        if sp[i] > 0.08:
            cur = math.atan2(vy[i], vx[i])
        elif cur is not None:
            cur += math.radians(gz[i]) * dts[i]
        head[i] = cur if cur is not None else 0.0
    us = s["us_cm"]; ang = np.radians(s["us_angle_deg"])
    hits = []
    ox0, oy0 = x0 - 1, y0 - 1
    onx, ony = int((x1 - x0 + 2) / OCC_CELL), int((y1 - y0 + 2) / OCC_CELL)
    logodds = np.zeros((ony, onx))
    for i in range(0, len(ts), 2):           # 25 Hz is plenty
        if not in_run(ts[i]) or us[i] <= 0 or not (sp[i] > 0.08 or cur is not None):
            continue
        d = us[i] / 100; hh = head[i] + ang[i]
        ex, ey = hx[i] + d * math.cos(hh), hy[i] + d * math.sin(hh)
        hits.append([int(ts[i]), round(ex, 3), round(ey, 3)])
        for f in np.arange(0, d - OCC_CELL, OCC_CELL / 2):
            gx_, gy_ = int((hx[i] + f * math.cos(hh) - ox0) / OCC_CELL), int((hy[i] + f * math.sin(hh) - oy0) / OCC_CELL)
            if 0 <= gx_ < onx and 0 <= gy_ < ony:
                logodds[gy_, gx_] -= 0.2
        gx_, gy_ = int((ex - ox0) / OCC_CELL), int((ey - oy0) / OCC_CELL)
        if 0 <= gx_ < onx and 0 <= gy_ < ony:
            logodds[gy_, gx_] += 0.9
    logodds = np.clip(logodds, -4, 4)

    meta = {}
    if (run / "SYNTHETIC.json").exists():
        meta = json.loads((run / "SYNTHETIC.json").read_text())
    obstacles = []
    for line in (run / "floor.txt").read_text().splitlines():
        p = line.split("#")[0].split()
        if len(p) == 6 and p[0] == "obstacle":
            obstacles.append([float(v) for v in p[2:]])
    out = {
        "run": run.name, "synthetic": bool(meta.get("synthetic")),
        "t_start_ms": int(t_start), "t_end_ms": int(t_end), "offset_ms": off,
        "markers": marks, "floor_bounds": [float(x0), float(y0), float(x1), float(y1)],
        "obstacles": obstacles, "person_truth": meta.get("person"),
        "track": [[int(t), round(float(x), 3), round(float(y), 3)] for t, x, y in zip(tt[::3], tx[::3], ty[::3])],
        "coverage": {"cell_m": CELL, "nx": nx, "ny": ny, "x0": float(x0), "y0": float(y0),
                     "model": f"POD = 1 - exp(-dwell/{TAU}s), sweep radius {R_SWEEP} m (illustrative)",
                     "snapshots": snaps,
                     "final_mean_pod": round(float(pod.mean()), 3),
                     "area_m2_pod_ge_0_5": round(float((pod >= 0.5).sum() * CELL * CELL), 2)},
        "alerts": alerts,
        "occupancy": {"hits": hits, "cell_m": OCC_CELL, "x0": ox0, "y0": oy0, "nx": onx, "ny": ony,
                      "logodds": np.round(logodds, 2).tolist()},
        "video": "overhead.mp4",
    }
    (run / "layers.json").write_text(json.dumps(out))
    summ = {"cells": nx * ny, "area_m2_pod_ge_0_5": out["coverage"]["area_m2_pod_ge_0_5"],
            "mean_pod": out["coverage"]["final_mean_pod"], "snapshots": len(snaps),
            "alerts": {k: sum(1 for al in alerts if al["kind"] == k) for k in sorted({al["kind"] for al in alerts})},
            "us_hits": len(hits)}
    print(json.dumps(summ))
    if a.emit:
        import inbox
        base = a.origin_epoch if a.origin_epoch else time.time() - (t_end - t_start) / 1000
        for al in alerts:
            if al["confidence"] <= 0:
                continue
            inbox.emit("dog1", al["kind"], al["confidence"], {"x": al["x"], "y": al["y"], "frame": "floor"},
                       None, t=base + (al["t_ms"] - t_start) / 1000, extra={"run": run.name, "source": al["source"]})
        print("emitted", sum(1 for al in alerts if al["confidence"] > 0), "alerts to inbox")


if __name__ == "__main__":
    main()
