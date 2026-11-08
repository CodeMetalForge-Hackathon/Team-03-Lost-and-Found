"""3D scene of one reconstructed run: floor, sensed wall patches, sonar beam, swept coverage.

Usage: scene.py OUT_DIR [--solution room_prior|sensor_only] [--eye 20,34]
Writes OUT_DIR/scene.ply, scene.glb (if trimesh loads), topdown.png, dogseye.png
"""
from __future__ import annotations
import math, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from common import Run, Coverage, sweep, cone_footprint, wall_patch, render_first_person, HALF_BEAM, NOSE_Z, NO_ECHO_M, WALL_H

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "vendor"))


def args():
    a = sys.argv[1:]
    out = Path(a[0]); sol = None; eye = None
    if "--solution" in a:
        sol = a[a.index("--solution") + 1]
    if "--eye" in a:
        eye = [float(v) for v in a[a.index("--eye") + 1].split(",")]
    return out, sol, eye


def cone_points(x, y, h, L, n_ax=25, n_ring=24):
    """Surface points of the 15° cone from the nose (z = 0.12 m), clipped at the floor."""
    pts = []
    f = np.array([math.cos(h), math.sin(h), 0]); r = np.array([-math.sin(h), math.cos(h), 0]); u = np.array([0, 0, 1.0])
    A = np.array([x, y, NOSE_Z])
    for s in np.linspace(0.02, L, n_ax):
        rad = s * math.tan(HALF_BEAM)
        for a in np.linspace(0, 2 * math.pi, n_ring, endpoint=False):
            p = A + s * f + rad * (math.cos(a) * r + math.sin(a) * u)
            if p[2] >= 0:
                pts.append(p)
    return pts


def write_ply(path, P, C):
    with open(path, "w") as fh:
        fh.write(f"ply\nformat ascii 1.0\ncomment dogeye reconstruction; local frame, metres; headings NOT measured\n"
                 f"element vertex {len(P)}\nproperty float x\nproperty float y\nproperty float z\n"
                 "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
        for p, c in zip(P, C):
            fh.write(f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f} {c[0]} {c[1]} {c[2]}\n")


def main():
    out, sol, eye = args()
    run = Run(out, sol)
    x0, x1, y0, y1 = run.bounds()
    cov = Coverage(x0, x1, y0, y1)
    sweep(run, cov, run.T + 1.0)
    # ---------------- point cloud ----------------
    P, C = [], []
    for gx in np.arange(x0, x1, 0.05):
        for gy in np.arange(y0, y1, 0.05):
            ci = min(int((gx - cov.x0) / cov.cell), cov.nx - 1); cj = min(int((gy - cov.y0) / cov.cell), cov.ny - 1)
            P.append((gx, gy, 0)); C.append((47, 129, 247) if cov.dwell[cj, ci] > 0 else (60, 64, 72))
    for w in run.walls:
        Q, width = wall_patch(w)
        for s in np.linspace(0, 1, 20):
            for v in np.linspace(0, 1, 12):
                p = Q[0] + s * (Q[1] - Q[0]) + v * (Q[3] - Q[0]); P.append(tuple(p)); C.append((201, 180, 88))
    for k in range(len(run.t)):
        P.append((run.x[k], run.y[k], NOSE_Z)); C.append((255, 138, 31))
    for tq in np.arange(0, run.T + 0.01, 1.0):
        x, y, h, d, _ = run.pose(tq)
        for p in cone_points(x, y, h, NO_ECHO_M if math.isnan(d) else d, n_ax=10, n_ring=12):
            P.append(tuple(p)); C.append((255, 190, 120))
    write_ply(out / "scene.ply", P, C)
    # ---------------- glb ----------------
    glb = "skipped"
    try:
        import trimesh
        meshes = []
        floor = trimesh.creation.box(extents=[x1 - x0, y1 - y0, 0.005])
        floor.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, -0.0025]); floor.visual.face_colors = [40, 44, 52, 255]
        meshes.append(floor)
        for w in run.walls:
            Q, width = wall_patch(w)
            b = trimesh.creation.box(extents=[0.01, width, WALL_H])
            ang = math.atan2(w["hy"], w["hx"])
            b.apply_transform(trimesh.transformations.rotation_matrix(ang, [0, 0, 1]))
            b.apply_translation([w["x"], w["y"], WALL_H / 2]); b.visual.face_colors = [201, 180, 88, 255]
            meshes.append(b)
        for tq in np.arange(0, run.T + 0.01, 2.0):
            x, y, h, d, _ = run.pose(tq)
            L = NO_ECHO_M if math.isnan(d) else d
            cn = trimesh.creation.cone(radius=L * math.tan(HALF_BEAM), height=L, sections=16)
            # trimesh cone: base at z=0, apex at z=L -> flip so apex is at the nose and it opens along heading
            cn.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
            cn.apply_translation([0, 0, L])
            cn.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
            cn.apply_transform(trimesh.transformations.rotation_matrix(h, [0, 0, 1]))
            cn.apply_translation([x, y, NOSE_Z]); cn.visual.face_colors = [255, 138, 31, 60]
            meshes.append(cn)
        for k in range(len(run.t)):
            s = trimesh.creation.icosphere(radius=0.012); s.apply_translation([run.x[k], run.y[k], NOSE_Z])
            s.visual.face_colors = [255, 138, 31, 255]; meshes.append(s)
        trimesh.Scene(meshes).export(out / "scene.glb"); glb = "ok"
    except Exception as e:  # noqa
        glb = f"skipped ({type(e).__name__}: {e})"
    # ---------------- top-down ----------------
    fig, ax = plt.subplots(figsize=(8, 7), dpi=130)
    fig.patch.set_facecolor("#0e1116"); ax.set_facecolor("#0b0e13")
    seen = np.ma.masked_where(cov.dwell <= 0, np.minimum(cov.dwell, 6))
    ax.imshow(seen, origin="lower", extent=[cov.x0, cov.x0 + cov.nx * cov.cell, cov.y0, cov.y0 + cov.ny * cov.cell],
              cmap="Blues", vmin=-2, vmax=6, alpha=0.85, interpolation="nearest")
    for tq in np.arange(0, run.T + 0.01, 1.0):
        x, y, h, d, _ = run.pose(tq)
        if not math.isnan(d):
            ax.add_patch(Polygon(cone_footprint(x, y, h, d), closed=True, fc="none", ec=(1, .54, .12, .25), lw=0.6))
    for w in run.walls:
        Q, width = wall_patch(w)
        ax.plot(Q[:2, 0], Q[:2, 1], color="#c9b458", lw=5, solid_capstyle="butt")
        ax.annotate(f"sensed surface\nd_min {w['d_min_cm']:.0f} cm", (w["x"], w["y"]), xytext=(w["x"] + 0.05 * w["hx"] + (0.04 if w["hy"] else 0), w["y"] + 0.05 * w["hy"] - 0.12 * abs(w["hx"]) - 0.02),
                    color="#c9b458", fontsize=7)
    ax.plot(run.x, run.y, "-", color="#ff8a1f", lw=1.5); ax.plot(run.x, run.y, "o", color="#ff8a1f", ms=2.5)
    ax.plot(run.x[0], run.y[0], "s", color="#3fb950", ms=8, label="start"); ax.plot(run.x[-1], run.y[-1], "X", color="#f85149", ms=9, label="end")
    last = run.pose(run.T)
    ax.add_patch(Polygon(cone_footprint(last[0], last[1], last[2], 0.9), closed=True, fc=(1, .54, .12, .12), ec="#ff8a1f", lw=0.8, ls="--"))
    ax.text(last[0] + 0.05, last[1] + 0.25, "no echo → open floor\n(beam drawn 0.9 m = where its\nlower edge meets the floor)", color="#ff8a1f", fontsize=6.5)
    marks = {"TILT": ("^", "#d29922"), "BARK": ("*", "#f85149"), "STILL": ("o", "#8b949e")}
    for a in run.alerts:
        x, y, h, d, _ = run.pose(a["t"]); m, c = marks.get(a["kind"], ("x", "#fff"))
        ax.plot(x, y + 0.03, m, color=c, ms=7 if a["kind"] == "BARK" else 4, mec="none")
    for k, c in [("TILT (gait bob)", "#d29922"), ("BARK (loud sound at arrival)", "#f85149"), ("STILL", "#8b949e")]:
        ax.plot([], [], marks[k.split()[0]][0], color=c, label=k)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal")
    ax.tick_params(colors="#8b949e", labelsize=7); [s.set_color("#2a313c") for s in ax.spines.values()]
    ax.set_xlabel("x (m, local frame)", color="#8b949e", fontsize=8); ax.set_ylabel("y (m)", color="#8b949e", fontsize=8)
    ax.legend(loc="lower right", fontsize=7, facecolor="#161b22", edgecolor="#2a313c", labelcolor="#e6edf3")
    lab = run.S["label"].split(": ", 1)
    ax.set_title(f"{run.meta['run']} · top-down · {lab[0]}\n{lab[1] if len(lab) > 1 else ''}", color="#e6edf3", fontsize=8, loc="left")
    fig.text(0.01, 0.01, "blue = swept beam coverage (15° cone, 0.1 s steps) · orange = sonar dead-reckoned track · gold = sensed surfaces. "
             "Positions from range only; no heading or odometry sensor.", color="#8b949e", fontsize=6.5)
    fig.savefig(out / "topdown.png", facecolor=fig.get_facecolor(), bbox_inches="tight"); plt.close(fig)
    # ---------------- dog's-eye ----------------
    if eye is None:
        ap = [l for l in run.legs if l["kind"] == "approach"]
        eye = [round((l["start"] + l["end"]) / 2) for l in ap[:2]] or [run.T / 2]
    fig, axs = plt.subplots(1, len(eye), figsize=(6.4 * len(eye), 4.3), dpi=120)
    axs = np.atleast_1d(axs); fig.patch.set_facecolor("#0e1116")
    for a, tq in zip(axs, eye):
        c2 = Coverage(x0, x1, y0, y1); sweep(run, c2, tq)
        render_first_person(a, run, tq, cov=c2)
    fig.suptitle(f"{run.meta['run']} · dog's-eye (first person from the ranger, 0.12 m) · rendered reconstruction, not a camera",
                 color="#e6edf3", fontsize=9)
    fig.savefig(out / "dogseye.png", facecolor=fig.get_facecolor(), bbox_inches="tight"); plt.close(fig)
    print(f"scene: {len(P)} points → scene.ply; glb {glb}; topdown.png; dogseye.png @ t={eye}; "
          f"covered {cov.seen().sum() * cov.cell ** 2:.2f} m² of floor (beam footprint)")


if __name__ == "__main__":
    main()
