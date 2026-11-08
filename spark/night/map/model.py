"""Persona prior + Clue Engine posterior on the 50 m feature grid.

PRIOR (per persona)
  1. Ring: Koester 2020 distance-from-IPP quantiles (25/50/75/95 %) -> piecewise-constant radial density
     (mass in each annulus / annulus area). 5 % spread from r95 out to the grid edge. Mass beyond 10 km is
     dropped and the grid renormalised (affects td_child, r95 = 11.3 km).
  2. Terrain class per cell: structure (building in cell) > water (<= 25 m of a water body) > road
     (<= persona track-offset q75 of a road) > drainage (<= 25 m of a stream) > linear (<= offset q75 of a trail)
     > other (woods/field/brush/scrub/rock: no land-cover layer, so lumped).
  3. Raking (iterative proportional fitting): the grid is rescaled until BOTH the mass per distance annulus
     matches the Table 3 quantiles AND the mass per terrain class matches the persona's find-location
     percentages (Koester 2020 Table 7, temperate). So "78 % of ASD subjects found in structures" becomes
     78 % of the prior mass in structure cells, and 50 % of the mass still lies inside the 50 % radius.
  4. Floor every cell at 2 % of its ring-only density (never zero out a region).
UNCERTAINTY: 40 Monte Carlo draws: quantiles x lognormal jitter (sd 1.6/sqrt(n), ~ sampling error), find-location
  percentages ~ Dirichlet(n x pct + 0.5). Per-cell coefficient of variation is returned with the mean.
POSTERIOR = prior x prod(LR_clue(cell)) x prod(1 - POD_searched(cell)), renormalised (Bayes with
  normalisation: Hill 2012 found 78 % of planners give subadditive probabilities, so the map always sums to 1).
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
F = dict(np.load(HERE / "features.npz"))
META = json.loads((HERE / "features_meta.json").read_text())
N = META["n"]; CELL = META["cell_m"]; HALF = META["half_m"]
CLASSES = ["structure", "water", "road", "drainage", "linear", "other"]

K20 = "Koester 2020, J. Search & Rescue 4(1):65-83"
PERSONAS = {
    "child_autistic": {
        "label": "Autistic child/adult (ASD), temperate", "verified": True, "n": 233,
        "q": [400, 900, 2300, 8000], "offset_q75": 46,
        "find": {"structure": 78, "road": 7, "linear": 0, "drainage": 1, "water": 5, "other": 8},
        "source": f"{K20}: Table 3 distances (n=233), Table 7 find location, track offset q75 46 m",
        "note": "Table 7 shows water finds 5 % ASD vs 8 % TD (temperate): not 'drawn to water'. Drowning scenario 2.8 % vs 0.5 % (Table 8)."},
    "td_child_1_16": {
        "label": "Typical child 1–16, temperate", "verified": True, "n": 903,
        "q": [300, 900, 2400, 11300], "offset_q75": 53,
        "find": {"structure": 34, "road": 18, "linear": 10, "drainage": 6, "water": 8, "other": 24},
        "source": f"{K20}: Table 3 distances (n=903), Table 7 find location, track offset q75 53 m", "note": ""},
    "hiker": {
        "label": "Hiker (ILLUSTRATIVE)", "verified": False, "n": 50, "q": [1000, 2000, 4000, 8000], "offset_q75": 50,
        "find": {"structure": 10, "road": 15, "linear": 30, "drainage": 5, "water": 5, "other": 35},
        "source": "illustrative placeholder, not from a table", "note": ""},
    "hunter": {
        "label": "Hunter (ILLUSTRATIVE)", "verified": False, "n": 50, "q": [1000, 2000, 4000, 9000], "offset_q75": 50,
        "find": {"structure": 5, "road": 10, "linear": 10, "drainage": 10, "water": 5, "other": 60},
        "source": "illustrative placeholder, not from a table", "note": ""},
    "dementia": {
        "label": "Dementia (ILLUSTRATIVE)", "verified": False, "n": 50, "q": [200, 500, 1200, 3000], "offset_q75": 15,
        "find": {"structure": 20, "road": 35, "linear": 20, "drainage": 10, "water": 5, "other": 10},
        "source": "illustrative placeholder; '50 % within 15 m of a linear feature' is from the research report, not verified", "note": ""},
}

# Clue Engine likelihood ratios. LR(cell) = 1 + (k - 1) * exp(-d^2 / (2 sigma^2)) for point clues.
EXPERT = "expert prior (hand-set, not calibrated)"
CLUES = {
    "witness_sighting": {"label": "Witness sighting", "k": 15, "sigma_m": 300, "grow_kmh": 1.5,
                         "prov": f"{EXPERT}; sigma grows 1.5 km/h with time since sighting"},
    "clothing_item": {"label": "Clothing / personal item found", "k": 10, "sigma_m": 400,
                      "prov": f"{EXPERT}. Detectability of clue-sized objects on trail: 100 % day / 94 % night (high-vis), 83 % / 43 % (low-vis), Koester 2020 POD study"},
    "footprint": {"label": "Footprint / track", "k": 6, "sigma_m": 250, "prov": EXPERT},
    "dog_interest": {"label": "Dog interest / alert", "k": 5, "sigma_m": 150, "prov": f"{EXPERT}; dog stand-in alerts are rover behaviour, not a trained dog"},
    "sound_contact": {"label": "Tap Three / sound contact", "k": 20, "sigma_m": 60, "prov": f"{EXPERT}; tap3 detector 0 confirmed FA in 7.8–12.5 h geophone negatives (night/tap3/RESULTS.md)"},
    "thermal_hit": {"label": "Thermal person detection", "k": 10, "sigma_m": 40, "prov": f"{EXPERT}; YOLO11n HIT-UAV Person mAP50 0.814 on a held-out group split (pass 2)"},
    "phone_fix": {"label": "Phone / Sky Fix position", "k": 25, "sigma_m": None,
                  "prov": f"{EXPERT}; sigma = reported uncertainty (ce)"},
    "searched_no_find": {"label": "Area searched, nothing found", "k": None, "sigma_m": None,
                         "prov": "POD = 1 - exp(-W·L/A) (exponential model, conservative). Sweep width W = 64 m day / 22 m night (Koester 2020 ESW experiment, adult target, temperate forest)"},
}

_E = -HALF + (np.arange(N) + .5) * CELL
_N = HALF - (np.arange(N) + .5) * CELL
EE, NN = np.meshgrid(_E, _N)


def classes(p):
    off = p["offset_q75"]
    c = np.full((N, N), 5, np.int8)                                # other
    c[F["trail"] <= max(off, 25)] = 4                              # linear
    c[F["stream"] <= 25] = 3                                       # drainage
    c[F["road"] <= max(off, 25)] = 2                               # road
    c[F["water"] <= 25] = 1                                        # water
    c[F["bcount"] > 0] = 0                                         # structure
    return c


def ring(q):
    r = F["r"]; r25, r50, r75, r95 = q
    edges = [0, r25, r50, r75, r95, max(HALF * math.sqrt(2), r95 + 1)]
    mass = [0.25, 0.25, 0.25, 0.20, 0.05]
    d = np.zeros_like(r)
    for a, b, m in zip(edges[:-1], edges[1:], mass):
        d[(r >= a) & (r < b)] = m / (math.pi * (b * b - a * a))
    return d


def prior_once(p, q=None, find=None, iters=30):
    """Iterative proportional fitting: start from the ring density, alternately rescale so that
    (a) each distance annulus holds its Koester quantile mass and (b) each terrain class holds its
    Table 7 find-location share. Converges to a grid matching both marginals."""
    q = p["q"] if q is None else q; find = p["find"] if find is None else find
    base = ring(q); base = base / base.sum(); cl = classes(p)
    r = F["r"]; r25, r50, r75, r95 = q
    edges = [0, r25, r50, r75, r95, 1e9]
    ann = np.digitize(r, edges[1:-1])                      # 0..4
    a_target = np.array([0.25, 0.25, 0.25, 0.20, 0.05])
    present_a = [i for i in range(5) if (ann == i).any()]
    a_target = a_target / a_target[present_a].sum()
    present = [i for i in range(len(CLASSES)) if (cl == i).any()]
    c_target = np.array([find[k] for k in CLASSES], float)
    c_target = c_target / c_target[present].sum()
    pr = base.copy()
    for _ in range(iters):
        for i in present_a:
            m = pr[ann == i].sum()
            if m > 0: pr[ann == i] *= a_target[i] / m
        for i in present:
            m = pr[cl == i].sum()
            if m > 0: pr[cl == i] *= c_target[i] / m
    # never zero out a region: floor each cell at 2 % of its ring-only density (a global 2 %-of-max floor,
    # as on the 1 km pass-1 grid, hands most of the mass to the far field on a 20 km grid)
    pr = np.maximum(pr, 0.02 * base)
    return pr / pr.sum(), cl


_cache = {}


def prior(name):
    if name in _cache:
        return _cache[name]
    p = PERSONAS[name]
    mean, cl = prior_once(p)
    rng = np.random.default_rng(0)
    sd = 1.6 / math.sqrt(p["n"])          # ~ sampling sd of a log-quantile for n subjects
    draws = []
    keys = CLASSES
    for _ in range(40):
        q = sorted(float(x * math.exp(rng.normal(0, sd))) for x in p["q"])
        alpha = np.array([p["find"][k] * p["n"] / 100 + 0.5 for k in keys])
        f = dict(zip(keys, rng.dirichlet(alpha) * 100))
        draws.append(prior_once(p, q, f)[0])
    D = np.stack(draws)
    cv = D.std(0) / (D.mean(0) + 1e-15)
    # achieved class mass (check that raking did what it says)
    mass = {k: round(float(mean[cl == i].sum()) * 100, 1) for i, k in enumerate(CLASSES)}
    _cache[name] = (mean, cv.astype(np.float32), cl, mass)
    return _cache[name]


def en_cell(e, n):
    return int((HALF - n) // CELL), int((e + HALF) // CELL)


def clue_lr(c: dict) -> np.ndarray:
    t = CLUES[c["type"]]
    if c["type"] == "searched_no_find":
        pod = float(c.get("pod", 0.5))
        lr = np.ones((N, N))
        poly = c.get("polygon_en")
        if poly:
            from matplotlib.path import Path as MPath
            inside = MPath(np.array(poly)).contains_points(np.c_[EE.ravel(), NN.ravel()]).reshape(N, N)
            lr[inside] = 1 - min(pod, 0.95)
        else:
            d = np.hypot(EE - c["e"], NN - c["n"])
            lr[d <= float(c.get("radius_m", 200))] = 1 - min(pod, 0.95)
        return lr
    sigma = t["sigma_m"]
    if c["type"] == "phone_fix":
        sigma = max(float(c.get("ce_m", 50)), 10)
    if c["type"] == "witness_sighting":
        sigma = sigma + t["grow_kmh"] * 1000 * float(c.get("hours_ago", 0))
    d2 = (EE - c["e"]) ** 2 + (NN - c["n"]) ** 2
    return 1 + (t["k"] - 1) * np.exp(-d2 / (2 * sigma * sigma))


def coverage_pod(cov_cells: list[dict]) -> np.ndarray:
    """cov_cells: [{e, n, pod, area_m2}] from projected dog runs -> per-map-cell POD (area-weighted)."""
    keep = np.ones((N, N))
    for c in cov_cells:
        r, k = en_cell(c["e"], c["n"])
        if 0 <= r < N and 0 <= k < N:
            frac = min(1.0, c["area_m2"] / (CELL * CELL))
            keep[r, k] *= (1 - min(c["pod"], 0.95)) ** frac
    return 1 - keep


def posterior(persona: str, clues: list[dict], pod_map: np.ndarray | None):
    pr, cv, cl, mass = prior(persona)
    post = pr.copy()
    for c in clues:
        if c.get("active", True):
            post *= clue_lr(c)
    if pod_map is not None:
        post *= (1 - pod_map)
    post /= post.sum()
    captured = float((pr * (pod_map if pod_map is not None else 0)).sum())
    return pr, post, cv, cl, mass, captured


def top_cells(post, cl, k=10):
    idx = np.argsort(post.ravel())[::-1][:k]
    out = []
    for i in idx:
        r, c = divmod(int(i), N)
        e, n = _E[c], _N[r]
        out.append({"r": r, "c": c, "e": float(e), "n": float(n), "p": float(post[r, c]),
                    "class": CLASSES[cl[r, c]], "dist_m": round(float(math.hypot(e, n))),
                    "why": f"{CLASSES[cl[r, c]]}, {round(math.hypot(e, n))} m from IPP"})
    return out
