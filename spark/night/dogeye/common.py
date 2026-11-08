"""Shared geometry for scene.py / fourd.py: interpolated pose, sonar cone, coverage raster, pinhole renderer."""
from __future__ import annotations
import csv, json, math
from pathlib import Path
import numpy as np

HALF_BEAM = math.radians(7.5)     # Grove ranger, ±~7.5° (15° cone)
NOSE_Z = 0.12                     # sensor height above the floor (m)
NO_ECHO_M = 0.9                   # beam length credited when there is no echo: the lower beam edge meets the floor at
                                  # 0.12 m / tan(7.5°) ≈ 0.91 m (conservative; the ranger's nominal reach is ~3.5 m)
WALL_H = 0.6
CELL = 0.05                       # scene coverage raster (m)


class Run:
    def __init__(self, out_dir: Path, solution: str | None = None):
        self.dir = Path(out_dir)
        self.meta = json.loads((self.dir / "legs.json").read_text())
        sols = self.meta["solutions"]
        self.sol = solution or ("room_prior" if "room_prior" in sols else "sensor_only")
        self.S = sols[self.sol]
        rows = list(csv.DictReader(open(self.dir / "track.csv")))
        f = lambda v: float(v) if v not in ("", None) else math.nan
        self.t = np.array([f(r["t"]) for r in rows])
        self.d = np.array([f(r["d_cm"]) for r in rows]) / 100.0
        self.x = np.array([f(r[f"{self.sol}_x"]) for r in rows])
        self.y = np.array([f(r[f"{self.sol}_y"]) for r in rows])
        self.hdg = np.array([f(r[f"{self.sol}_hdg"]) for r in rows])
        self.hid = np.array([int(r["heading_id"]) for r in rows])
        self.state = [r["state"] for r in rows]
        self.act = np.array([f(r["activity"]) for r in rows])
        self.temp = np.array([f(r["temp_c"]) for r in rows])
        self.hum = np.array([f(r["humidity"]) for r in rows])
        self.therm = np.array([f(r["therm_c"]) for r in rows])
        self.alerts = self.meta["alerts"]
        self.legs = self.meta["legs"]
        self.walls = [w for w in self.S["walls"] if w]
        self.T = float(self.t[-1])

    def pose(self, tq: float):
        """Interpolated (x, y, heading_rad, d_m or nan, idx). Heading is interpolated only across turns, for display."""
        i = int(np.clip(np.searchsorted(self.t, tq, side="right") - 1, 0, len(self.t) - 1))
        j = min(i + 1, len(self.t) - 1)
        w = 0.0 if j == i else float(np.clip((tq - self.t[i]) / (self.t[j] - self.t[i]), 0, 1))
        x = self.x[i] + (self.x[j] - self.x[i]) * w
        y = self.y[i] + (self.y[j] - self.y[i]) * w
        h0, h1 = math.radians(self.hdg[i]), math.radians(self.hdg[j])
        dh = (h1 - h0 + math.pi) % (2 * math.pi) - math.pi
        h = h0 + dh * w
        di, dj = self.d[i], self.d[j]
        if math.isnan(di) or math.isnan(dj) or self.hid[i] != self.hid[j]:
            d = di if w < 0.5 else dj
        else:
            d = di + (dj - di) * w
        return x, y, h, d, i

    def bounds(self, pad=0.35):
        xs = list(self.x) + [w["x"] for w in self.walls]
        ys = list(self.y) + [w["y"] for w in self.walls]
        return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad


def cone_footprint(x, y, h, L, n=12):
    """2D floor footprint of the 15° cone (triangle-ish fan) from the nose, length L."""
    angs = np.linspace(h - HALF_BEAM, h + HALF_BEAM, n)
    return np.array([[x, y]] + [[x + L * math.cos(a), y + L * math.sin(a)] for a in angs])


def wall_patch(w):
    """Sensed surface patch: centred at the wall point, perpendicular to the heading. Returns 4 3D corners."""
    d = w["d_min_cm"] / 100.0
    width = 2 * d * math.tan(HALF_BEAM) + 0.20
    hx, hy = w["hx"], w["hy"]; px, py = -hy, hx
    c = np.array([w["x"], w["y"]])
    a = c + (width / 2) * np.array([px, py]); b = c - (width / 2) * np.array([px, py])
    return np.array([[a[0], a[1], 0], [b[0], b[1], 0], [b[0], b[1], WALL_H], [a[0], a[1], WALL_H]]), width


class Coverage:
    """Swept-cone coverage raster (dwell seconds per cell) on a fixed grid."""
    def __init__(self, x0, x1, y0, y1, cell=CELL):
        self.x0, self.y0, self.cell = x0, y0, cell
        self.nx = int(math.ceil((x1 - x0) / cell)); self.ny = int(math.ceil((y1 - y0) / cell))
        self.dwell = np.zeros((self.ny, self.nx))
        gx = x0 + (np.arange(self.nx) + .5) * cell; gy = y0 + (np.arange(self.ny) + .5) * cell
        self.GX, self.GY = np.meshgrid(gx, gy)

    def add(self, x, y, h, L, dt):
        dx, dy = self.GX - x, self.GY - y
        r = np.hypot(dx, dy)
        ang = np.abs((np.arctan2(dy, dx) - h + np.pi) % (2 * np.pi) - np.pi)
        inside = (r <= L) & ((ang <= HALF_BEAM) | (r < self.cell))
        self.dwell[inside] += dt

    def seen(self):
        return self.dwell > 0


def sweep(run: Run, cov: Coverage, t_end: float, dt=0.1, t_start=0.0):
    t = t_start
    while t < t_end - 1e-9:
        x, y, h, d, i = run.pose(t)
        j = min(i + 1, len(run.t) - 1)
        if run.hid[i] != run.hid[j] or (j > i and run.hdg[i] != run.hdg[j]):   # turning: heading unknown → no credit
            t += dt; continue
        cov.add(x, y, h, NO_ECHO_M if math.isnan(d) else d, dt)
        t += dt


# ---------------- pinhole renderer (first person) ----------------
def _clip_near(P, near=0.02):
    out = []
    n = len(P)
    for k in range(n):
        a, b = P[k], P[(k + 1) % n]
        ina, inb = a[2] > near, b[2] > near
        if ina:
            out.append(a)
        if ina != inb:
            s = (near - a[2]) / (b[2] - a[2]); out.append(a + s * (b - a))
    return np.array(out)


def render_first_person(ax, run: Run, tq: float, fov_deg=90, W=640, H=400, cov: Coverage | None = None):
    """Draw what the nose-mounted ranger 'sees' at time tq onto a matplotlib axes (pixel coords)."""
    from matplotlib.patches import Polygon, Circle
    x, y, h, d, i = run.pose(tq)
    C = np.array([x, y, NOSE_Z]); f = np.array([math.cos(h), math.sin(h), 0.0])
    up = np.array([0, 0, 1.0]); r = np.cross(f, up)
    fpx = (W / 2) / math.tan(math.radians(fov_deg) / 2)

    def cam(Pw):
        Q = np.asarray(Pw, float) - C
        return np.stack([Q @ r, Q @ up, Q @ f], axis=-1)

    def proj(Pc):
        return np.stack([W / 2 + fpx * Pc[:, 0] / Pc[:, 2], H / 2 - fpx * Pc[:, 1] / Pc[:, 2]], axis=-1)

    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.set_aspect("equal"); ax.axis("off")
    ax.add_patch(Polygon([[0, 0], [W, 0], [W, H], [0, H]], closed=True, fc="#05070a", ec="none"))
    polys = []
    # floor tiles 10 cm, out to 2.5 m around the dog; tinted by coverage
    g = 0.10; R = 2.5
    for gx in np.arange(math.floor((x - R) / g) * g, x + R, g):
        for gy in np.arange(math.floor((y - R) / g) * g, y + R, g):
            P = np.array([[gx, gy, 0], [gx + g, gy, 0], [gx + g, gy + g, 0], [gx, gy + g, 0]])
            Pc = _clip_near(cam(P))
            if len(Pc) < 3:
                continue
            seen = False
            if cov is not None:
                ci = int((gx + g / 2 - cov.x0) / cov.cell); cj = int((gy + g / 2 - cov.y0) / cov.cell)
                seen = 0 <= ci < cov.nx and 0 <= cj < cov.ny and cov.dwell[cj, ci] > 0
            chk = (int(round(gx / g)) + int(round(gy / g))) % 2
            col = ("#1d4f8f" if chk else "#22599f") if seen else ("#1a1f27" if chk else "#151a21")
            polys.append((Pc[:, 2].mean(), proj(Pc), col, 1.0, None))
    for w in run.walls:
        P, width = wall_patch(w)
        Pc = _clip_near(cam(P))
        if len(Pc) >= 3:
            polys.append((Pc[:, 2].mean() - 0.01, proj(Pc), "#c9b458", 0.92, "sensed surface"))
    for dep, pts, col, al, lab in sorted(polys, key=lambda p: -p[0]):
        ax.add_patch(Polygon(pts, closed=True, fc=col, ec="#0b0e13" if lab is None else "#000", lw=0.3, alpha=al))
        if lab and dep < 4:
            cx, cy = pts.mean(axis=0)
            if 0 < cx < W and 0 < cy < H:
                ax.text(cx, cy, lab, color="#000", ha="center", va="center", fontsize=8, weight="bold")
    # beam: camera is at the apex, so the 15° cone is a circle of angular radius 7.5° about the view axis
    rb = fpx * math.tan(HALF_BEAM)
    ax.add_patch(Circle((W / 2, H / 2), rb, fc=(1, .54, .12, .18), ec="#ff8a1f", lw=1.5))
    # floor intersection of the lower beam edge: 0.12 / tan(7.5°) ≈ 0.91 m
    ax.plot([W / 2 - 6, W / 2 + 6], [H / 2, H / 2], color="#ff8a1f", lw=1); ax.plot([W / 2, W / 2], [H / 2 - 6, H / 2 + 6], color="#ff8a1f", lw=1)
    dtxt = "no echo (open floor)" if math.isnan(d) else f"{d * 100:.0f} cm"
    ax.text(8, 16, f"t = {tq:5.1f} s   range {dtxt}   {run.state[i]}   act {run.act[i]:.1f}",
            color="#e6edf3", fontsize=9, family="monospace")
    ax.text(8, H - 8, f"dog's-eye · nose 0.12 m · FOV {fov_deg}° · headings: {run.sol.upper().replace('_', '-')} (not measured)",
            color="#8b949e", fontsize=7)
