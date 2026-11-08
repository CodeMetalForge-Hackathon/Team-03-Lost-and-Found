"""4D = the 3D reconstruction over time. replay.mp4 (matplotlib frames → ffmpeg) + replay.html (self-contained, offline).

Usage: fourd.py OUT_DIR [--speed 2] [--fps 30] [--video PATH]
"""
from __future__ import annotations
import json, math, os, subprocess, sys, shutil, tempfile
from multiprocessing import Pool
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Circle
from common import Run, Coverage, sweep, cone_footprint, wall_patch, render_first_person, NO_ECHO_M

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vendor"))
A = sys.argv[1:]
OUT = Path(A[0])
SPEED = float(A[A.index("--speed") + 1]) if "--speed" in A else 2.0
FPS = int(A[A.index("--fps") + 1]) if "--fps" in A else 30
VIDEO = Path(A[A.index("--video") + 1]) if "--video" in A else HERE.parent / "data/dog/run10/video.mp4"
MARK = {"TILT": ("^", "#d29922"), "BARK": ("*", "#f85149"), "STILL": ("o", "#8b949e")}
RUN = None


def init():
    global RUN
    RUN = Run(OUT)


def frame(args):
    k, tq, path = args
    run = RUN
    x0, x1, y0, y1 = run.bounds()
    cov = Coverage(x0, x1, y0, y1); sweep(run, cov, tq)
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100); fig.patch.set_facecolor("#0e1116")
    # ---- top-down ----
    ax = fig.add_axes([0.03, 0.36, 0.40, 0.58]); ax.set_facecolor("#0b0e13")
    seen = np.ma.masked_where(cov.dwell <= 0, np.minimum(cov.dwell, 6))
    ax.imshow(seen, origin="lower", extent=[cov.x0, cov.x0 + cov.nx * cov.cell, cov.y0, cov.y0 + cov.ny * cov.cell],
              cmap="Blues", vmin=-2, vmax=6, alpha=.85, interpolation="nearest")
    for hid, w in enumerate(run.S["walls"]):
        if not w:
            continue
        first = run.t[run.hid == hid][0]
        if tq >= first:                                  # a surface appears once the beam has found it
            Q, _ = wall_patch(w); ax.plot(Q[:2, 0], Q[:2, 1], color="#c9b458", lw=5, solid_capstyle="butt")
    m = run.t <= tq
    ax.plot(run.x[m], run.y[m], "-", color="#ff8a1f", lw=1.2, alpha=.8)
    x, y, h, d, i = run.pose(tq)
    L = NO_ECHO_M if math.isnan(d) else d
    ax.add_patch(Polygon(cone_footprint(x, y, h, L), closed=True, fc=(1, .54, .12, .25), ec="#ff8a1f", lw=1, ls="--" if math.isnan(d) else "-"))
    amp = 0.0012 * run.act[i]                           # gait vibration drawn ∝ activity
    jx, jy = amp * math.sin(k * 2.1), amp * math.cos(k * 3.3)
    ax.add_patch(Circle((x + jx, y + jy), 0.03, fc="#ff8a1f", ec="#000"))
    ax.plot([x, x + 0.06 * math.cos(h)], [y, y + 0.06 * math.sin(h)], color="#000", lw=2)
    for a in run.alerts:
        if a["t"] <= tq:
            ax_, ay_, *_ = run.pose(a["t"]); mk, c = MARK.get(a["kind"], ("x", "#fff"))
            ax.plot(ax_, ay_ + 0.03, mk, color=c, ms=8 if a["kind"] == "BARK" else 4, mec="none")
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal")
    ax.tick_params(colors="#8b949e", labelsize=6); [s.set_color("#2a313c") for s in ax.spines.values()]
    ax.set_title(f"top-down · headings {run.sol.upper().replace('_', '-')} (NOT measured)", color="#e6edf3", fontsize=8, loc="left")
    # ---- dog's-eye ----
    ax2 = fig.add_axes([0.45, 0.42, 0.37, 0.52])
    render_first_person(ax2, run, tq, cov=cov)
    # ---- video slot ----
    ax3 = fig.add_axes([0.835, 0.42, 0.155, 0.52]); ax3.set_facecolor("#05070a"); ax3.set_xticks([]); ax3.set_yticks([])
    [s.set_color("#2a313c") for s in ax3.spines.values()]
    ax3.text(0.5, 0.5, "phone video slot\n\n(Franco's run-10 video\nnot provided yet)" if not VIDEO.exists() else "phone video:\nsee replay.html",
             color="#8b949e", ha="center", va="center", fontsize=8, transform=ax3.transAxes)
    # ---- strip charts ----
    ts = run.t
    a1 = fig.add_axes([0.05, 0.22, 0.93, 0.11]); a2 = fig.add_axes([0.05, 0.12, 0.93, 0.08], sharex=a1)
    a3 = fig.add_axes([0.05, 0.03, 0.93, 0.07], sharex=a1)
    for a in (a1, a2, a3):
        a.set_facecolor("#0b0e13"); a.tick_params(colors="#8b949e", labelsize=6); [s.set_color("#2a313c") for s in a.spines.values()]
        a.axvline(tq, color="#ff8a1f", lw=1)
    dcm = run.d * 100
    a1.plot(ts, dcm, "-o", color="#c9d1d9", ms=2, lw=1)
    lost = np.isnan(dcm)
    for t_ in ts[lost]:
        a1.axvspan(t_ - .5, t_ + .5, color="#3fb950", alpha=.08, lw=0)
    for a in run.alerts:
        mk, c = MARK.get(a["kind"], ("x", "#fff"))
        a1.plot(a["t"], 98, mk, color=c, ms=7 if a["kind"] == "BARK" else 4, alpha=1 if a["t"] <= tq else .25)
    for l in run.legs:
        a1.text((l["start"] + l["end"]) / 2, 2, l["kind"], color="#8b949e", fontsize=5.5, ha="center")
    a1.set_ylim(0, 105); a1.set_ylabel("range cm", color="#8b949e", fontsize=7)
    a1.text(0.995, 0.85, "▲ TILT (gait bob)  ★ BARK (loud sound)  ● STILL   green = no echo (open floor)", transform=a1.transAxes,
            ha="right", color="#8b949e", fontsize=6)
    a2.fill_between(ts, 0, run.act, color="#ff8a1f", alpha=.35, step="mid"); a2.axhline(6, color="#8b949e", lw=.5, ls=":")
    a2.set_ylabel("activity", color="#8b949e", fontsize=7)
    a3.plot(ts, run.therm, color="#f85149", lw=1, label="therm_c (contact, NOT IR)")
    a3.plot(ts, run.temp, color="#d29922", lw=1, label="temp_c (DHT11)")
    a3b = a3.twinx(); a3b.plot(ts, run.hum, color="#2f81f7", lw=1, label="humidity %"); a3b.tick_params(colors="#8b949e", labelsize=6)
    a3.legend(loc="upper left", fontsize=5.5, facecolor="#161b22", edgecolor="#2a313c", labelcolor="#e6edf3", ncol=2)
    a3b.legend(loc="upper right", fontsize=5.5, facecolor="#161b22", edgecolor="#2a313c", labelcolor="#e6edf3")
    a1.set_xlim(0, run.T + 1); plt.setp(a1.get_xticklabels(), visible=False); plt.setp(a2.get_xticklabels(), visible=False)
    fig.text(0.03, 0.965, f"{run.meta['run']} · dog's-eye 4D replay · REAL range/IMU/sound stream · positions dead-reckoned from range only "
             f"· {SPEED:g}× · t = {tq:4.1f} s", color="#e6edf3", fontsize=9)
    fig.savefig(path, facecolor=fig.get_facecolor()); plt.close(fig)
    return k


def mp4():
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    run = Run(OUT)
    n = int(math.ceil((run.T + 1.0) / SPEED * FPS))
    tmp = Path(tempfile.mkdtemp(prefix="dogeye_", dir=str(HERE)))
    jobs = [(k, min(k * SPEED / FPS, run.T + 0.99), str(tmp / f"f{k:05d}.png")) for k in range(n)]
    with Pool(min(12, os.cpu_count() or 4), initializer=init) as p:
        for _ in p.imap_unordered(frame, jobs, chunksize=8):
            pass
    subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(tmp / "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-movflags", "+faststart", str(OUT / "replay.mp4")], check=True)
    shutil.copy(tmp / f"f{n // 2:05d}.png", OUT / "replay_midframe.png")
    shutil.rmtree(tmp)
    return n / FPS


def html():
    run = Run(OUT)
    x0, x1, y0, y1 = run.bounds()
    frames, cov = [], Coverage(x0, x1, y0, y1)
    tq, step = 0.0, 0.1
    snaps = []
    while tq <= run.T + 1e-6:
        x, y, h, d, i = run.pose(tq)
        frames.append([round(tq, 2), round(x, 4), round(y, 4), round(h, 4), None if math.isnan(d) else round(d, 3), i])
        if abs(tq - round(tq)) < 1e-6:
            snaps.append(np.flatnonzero(cov.dwell.ravel() > 0).tolist())
        sweep(run, cov, tq + step, t_start=tq)
        tq = round(tq + step, 2)
    walls = []
    for hid, w in enumerate(run.S["walls"]):
        if w:
            Q, width = wall_patch(w)
            walls.append(dict(a=Q[0, :2].round(4).tolist(), b=Q[1, :2].round(4).tolist(), t=float(run.t[run.hid == hid][0]), d_min=w["d_min_cm"]))
    nan = lambda a: [None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), 2) for v in a]
    D = dict(run=run.meta["run"], sol=run.sol, label=run.S["label"], bounds=[x0, x1, y0, y1],
             grid=dict(x0=cov.x0, y0=cov.y0, cell=cov.cell, nx=cov.nx, ny=cov.ny), snaps=snaps, frames=frames, walls=walls,
             t=run.t.tolist(), d=nan(run.d * 100), act=nan(run.act), state=run.state, therm=nan(run.therm), temp=nan(run.temp),
             hum=nan(run.hum), alerts=run.alerts, legs=[{k: l[k] for k in ("start", "end", "kind", "d_min", "d_max", "mean_speed_cm_s", "events")} for l in run.legs],
             x=nan(run.x), y=nan(run.y), video="video.mp4" if VIDEO.exists() else None, T=run.T, no_echo_m=NO_ECHO_M)
    if VIDEO.exists():
        shutil.copy(VIDEO, OUT / "video.mp4")
    tpl = (HERE / "replay_template.html").read_text()
    (OUT / "replay.html").write_text(tpl.replace("/*__DATA__*/null", json.dumps(D, separators=(",", ":"))))


if __name__ == "__main__":
    html()
    if "--html-only" not in A:
        L = mp4()
        print(f"replay.mp4: {L:.1f} s at {FPS} fps ({SPEED:g}×); replay.html written")
    else:
        print("replay.html written")
