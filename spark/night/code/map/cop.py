"""Common operating picture (COP): persona prior x clue LRs + sensor probability fields − searched coverage.

  base   = normalise(prior x prod LR(positive clues))                     (sums to 1)
  F_i    = m_i x g_i,  g_i a unit-mass kernel on the plane (mass falling outside the 20 km grid is lost),
           m_i = modality_weight[kind] x confidence  (Sky Fix: skyfix_weight x 1)
  mix    = base + sum_i F_i
  POD    = 1 − (1−POD_dog)(1−POD_team)(1−POD_drone)                       (independent sweeps)
  COP    = normalise(mix x (1 − POD))
"Minus searched coverage" is applied multiplicatively (Bayes: P(subject in cell | not found there)); a literal
subtraction could go negative.

Kernels: Tap Three = Gaussian at the sensor, sigma = clip(ref_sigma x ref_strength / strength); Perch = Gaussian
at the perch point; thermal = uniform disk under the drone footprint; dog alert = Gaussian at the dog's position;
Sky Fix = Gaussian at the solved position with sigma = its confidence radius (ce). All widths are hand-set.
"""
from __future__ import annotations
import json, math
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
R = 6371008.8
SOURCES = ["tap3", "perch", "thermal", "dog", "skyfix", "other"]
SOURCE_LABEL = {"tap3": "Tap Three (contact mic)", "perch": "Perch and Listen (acoustic)", "thermal": "Thermal (drone)",
                "dog": "Dog stand-in alerts", "skyfix": "Sky Fix self-fix (phone)", "other": "other sensors"}


class Grid:
    def __init__(self, n: int, cell: float, half: float, lat0: float, lon0: float):
        self.n, self.cell, self.half, self.lat0, self.lon0 = n, cell, half, lat0, lon0
        c = -half + (np.arange(n) + .5) * cell
        self.E, self.N = np.meshgrid(c, -c)          # row 0 = north

    def ll2en(self, lat, lon):
        return (math.radians(lon - self.lon0) * R * math.cos(math.radians(self.lat0)), math.radians(lat - self.lat0) * R)

    def en2ll(self, e, n):
        return self.lat0 + math.degrees(n / R), self.lon0 + math.degrees(e / (R * math.cos(math.radians(self.lat0))))

    def cell_of(self, e, n):
        return int((self.half - n) // self.cell), int((e + self.half) // self.cell)

    def gaussian(self, e, n, sigma):
        """Unit mass on the plane; cells get density x cell area (mass beyond the grid is dropped)."""
        sigma = max(float(sigma), self.cell / 4)
        d2 = (self.E - e) ** 2 + (self.N - n) ** 2
        return np.exp(-d2 / (2 * sigma * sigma)) * (self.cell ** 2) / (2 * math.pi * sigma * sigma)

    def disk(self, e, n, r):
        r = max(float(r), self.cell / 2)
        m = ((self.E - e) ** 2 + (self.N - n) ** 2) <= r * r
        if not m.any():
            g = np.zeros_like(self.E)
            rr, cc = self.cell_of(e, n)
            if 0 <= rr < self.n and 0 <= cc < self.n:
                g[rr, cc] = 1.0
            return g
        return m / m.sum()          # unit mass spread evenly over the cells under the footprint


def source_of(kind: str, sensor: str) -> str:
    k, s = kind.lower(), sensor.lower()
    if k.startswith("tap") or s.startswith("tap"):
        return "tap3"
    if k.startswith("acoustic") or s.startswith("perch"):
        return "perch"
    if "thermal" in k or "rgb" in k:
        return "thermal"
    if s.startswith("dog") or k.startswith("dog") or k in ("sound_spike", "knock", "shout"):
        return "dog"
    if "skyfix" in k or "skyfix" in s:
        return "skyfix"
    return "other"


def event_field(det: dict, grid: Grid, cfg: dict, floor_to_en) -> dict | None:
    """One inbox detection -> {source, mass, e, n, sigma, kernel, field}."""
    F = cfg["fields"]; pos = det.get("position") or {}
    if "lat" in pos and "lon" in pos:
        e, n = grid.ll2en(float(pos["lat"]), float(pos["lon"]))
    elif pos.get("x") is not None and pos.get("y") is not None:
        e, n = floor_to_en(float(pos["x"]), float(pos["y"]))
    else:
        return None
    kind, sensor = det.get("kind", ""), det.get("sensor", "")
    src = source_of(kind, sensor)
    w = cfg["modality_weight"].get(kind, cfg["modality_weight"]["default"])
    mass = w * float(det.get("confidence", 0))
    ex = det.get("extra") or {}
    if src == "tap3":
        st = max(float(ex.get("strength") or F["tap_strength_ref"]), 1e-3)
        sigma = min(max(F["tap_sigma_ref_m"] * F["tap_strength_ref"] / st, F["tap_sigma_min_m"]), F["tap_sigma_max_m"])
        g, kern = grid.gaussian(e, n, sigma), f"Gaussian σ={sigma:.0f} m (strength {st:.1f})"
    elif src == "perch":
        sigma = F["acoustic_sigma_m"]; g, kern = grid.gaussian(e, n, sigma), f"Gaussian σ={sigma:.0f} m at the perch"
    elif src == "thermal":
        r = float(ex.get("footprint_m") or F["thermal_footprint_m"]); sigma = r
        g, kern = grid.disk(e, n, r), f"disk r={r:.0f} m (drone footprint)"
    elif src == "dog":
        sigma = F["dog_sigma_m"]; g, kern = grid.gaussian(e, n, sigma), f"Gaussian σ={sigma:.0f} m at the dog"
    else:
        sigma = F["default_sigma_m"]; g, kern = grid.gaussian(e, n, sigma), f"Gaussian σ={sigma:.0f} m"
    return {"source": src, "kind": kind, "sensor": sensor, "mass": mass, "e": e, "n": n, "sigma": sigma,
            "kernel": kern, "field": mass * g, "mass_on_grid": float((mass * g).sum())}


def skyfix_fixes(cot_dir: Path, grid: Grid, cfg: dict, limit: int = 200) -> list[dict]:
    """Read Sky Fix CoT files read-only -> ring fields at the solved position (sigma = ce)."""
    out = []
    if not cot_dir.exists():
        return out
    files = sorted(cot_dir.glob("*.xml"), key=lambda p: p.stat().st_mtime)[-limit:]
    for p in files:
        try:
            ev = ET.parse(p).getroot(); pt = ev.find("point")
            lat, lon, ce = float(pt.get("lat")), float(pt.get("lon")), float(pt.get("ce"))
        except Exception:
            continue
        e, n = grid.ll2en(lat, lon)
        mass = cfg["fields"]["skyfix_weight"]
        g = grid.gaussian(e, n, ce)
        out.append({"source": "skyfix", "kind": "skyfix_fix", "sensor": ev.get("uid"), "mass": mass, "e": e, "n": n,
                    "sigma": ce, "kernel": f"Gaussian σ=ce={ce:.0f} m at the solved position", "field": mass * g,
                    "mass_on_grid": float((mass * g).sum()), "lat": lat, "lon": lon, "file": p.name})
    return out


def sum_fields(fields: list[dict], shape) -> dict[str, np.ndarray]:
    layers = {s: np.zeros(shape) for s in SOURCES}
    for f in fields:
        layers[f["source"]] += f["field"]
    return layers


def combine_pod(*pods) -> np.ndarray:
    keep = None
    for p in pods:
        if p is None:
            continue
        keep = (1 - p) if keep is None else keep * (1 - p)
    return 1 - keep if keep is not None else None


def drone_pod(track: list[dict], t_rel: float | None, grid: Grid, pod_per_pass: float) -> np.ndarray:
    """Each photo up to t_rel sweeps its footprint (axis-aligned rectangle) once with pod_per_pass."""
    keep = np.ones_like(grid.E)
    for s in track:
        if t_rel is not None and s["t_rel"] > t_rel:
            break
        w, h = s["footprint_m"]
        m = (np.abs(grid.E - s["e"]) <= w / 2) & (np.abs(grid.N - s["n"]) <= h / 2)
        keep[m] *= (1 - pod_per_pass)
    return 1 - keep


def disk_pod(cells: list[dict], grid: Grid) -> np.ndarray:
    """Team sweeps: [{e, n, radius_m, pod}] -> POD map."""
    keep = np.ones_like(grid.E)
    for c in cells:
        m = ((grid.E - c["e"]) ** 2 + (grid.N - c["n"]) ** 2) <= c["radius_m"] ** 2
        keep[m] *= (1 - min(float(c["pod"]), 0.95))
    return 1 - keep


def cop(base: np.ndarray, layers: dict[str, np.ndarray], pod: np.ndarray | None,
        enabled: set[str] | None = None) -> np.ndarray:
    mix = base / base.sum()
    for s, L in layers.items():
        if enabled is None or s in enabled:
            mix = mix + L
    if pod is not None:
        mix = mix * (1 - pod)
    return mix / mix.sum()


def next_best_action(c: np.ndarray, pod: np.ndarray | None, grid: Grid, cfg: dict, tasked: set = frozenset()) -> dict:
    """Highest-COP cell that is unsearched (POD < unsearched_pod_max) and not already tasked.
    ETAs are straight-line, terrain-free: team = dist / walk speed; drone = launch time + dist / drone speed."""
    lim = cfg["coverage"]["unsearched_pod_max"]
    score = c.copy()
    if pod is not None:
        score[pod >= lim] = -1
    for (r, k) in tasked:
        score[r, k] = -1
    i = int(np.argmax(score)); r, k = divmod(i, grid.n)
    if score[r, k] < 0:
        return {"none": True}
    e, n = float(grid.E[r, k]), float(grid.N[r, k]); lat, lon = grid.en2ll(e, n)
    A = cfg["assets"]
    teams = []
    for t in A["teams"]:
        te, tn = grid.ll2en(t["lat"], t["lon"]); d = math.hypot(e - te, n - tn)
        teams.append({"id": t["id"], "dist_m": round(d), "eta_min": round(d / A["walk_mps"] / 60, 1)})
    team = min(teams, key=lambda x: x["eta_min"])
    D = A["drone"]; de, dn = grid.ll2en(D["lat"], D["lon"]); dd = math.hypot(e - de, n - dn)
    drone = {"id": D["id"], "dist_m": round(dd), "eta_min": round((D.get("launch_s", 0) + dd / D["speed_mps"]) / 60, 1)}
    asset = "drone" if drone["eta_min"] <= team["eta_min"] else "team"
    cell_id = f"R{r:03d}C{k:03d}"
    return {"cell": [r, k], "cell_id": cell_id, "e": round(e), "n": round(n), "lat": lat, "lon": lon,
            "p": float(c[r, k]), "pod": float(pod[r, k]) if pod is not None else 0.0, "asset": asset,
            "drone": drone, "team": team,
            "text": (f"Suggest: {'drone' if asset == 'drone' else team['id']} to {cell_id} "
                     f"({lat:.5f}, {lon:.5f}), ETA {drone['eta_min'] if asset == 'drone' else team['eta_min']} min "
                     f"({'team' if asset == 'drone' else 'drone'} {team['eta_min'] if asset == 'drone' else drone['eta_min']} min)"),
            "basis": "highest COP cell with POD < %.2f, not already tasked; straight-line ETAs, terrain-free" % lim}
