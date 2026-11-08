"""Sky Fix skyline solver: daytime photo + focal length + a last-known-fix prior -> position, heading, ring.

1. Horizon: SAM 2 sky mask (fallback DP gradient) -> horizon elevation per column (horizon.py).
2. Candidates: 360-deg terrain horizon profiles on a 1 km grid within +/-25 km of the PRIOR (dem.py), cached.
   Honest framing: an aircrew member knows the last fix to tens of km; we search a 51 x 51 km box around it.
3. Match: for every cell and every heading (1 deg), compare the photo horizon (resampled to 1-deg azimuth
   steps; camera pitch unknown -> means removed) with the profile window. Score options:
   'ncc'  = Pearson correlation (spec default);  'rms' = -RMS of mean-removed difference (deg).
4. Output: best cell, heading (camera centre azimuth), score map, ring = radius from the best cell that
   contains all cells in the top 5 % of scores (spec definition).
"""
from __future__ import annotations
import math, pathlib, time, os
from multiprocessing import Pool
import numpy as np
from PIL import Image

import dem as D
import horizon as HZ

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_SCORE = os.environ.get("SKYFIX_SKYLINE_SCORE", "rms_detrend")
GRID_STEP_KM = float(os.environ.get("SKYFIX_GRID_STEP", "0.5"))  # spec baseline 1.0; 0.5 chosen on DEV (40% vs 30% within 5 km, oracle horizon)
CONF_RING_FLOOR_KM = 5.0
CONF_REL_MARGIN = 0.15  # chosen on the CH1 DEV split only (see WORKLOG); fixes below this are flagged AMBIGUOUS
_DEMS = {}


def _dem(name: str = "swiss"):
    if name not in _DEMS:
        lat_r, lon_r, ddir = D.REGIONS[name]
        D.build_mosaic(name, lat_r, lon_r, dem_dir=ddir)
        d = D.DEM(name)
        d.a = np.ascontiguousarray(d.a)
        _DEMS[name] = d
    return _DEMS[name]


def dem_for(lat: float, lon: float, margin_deg: float = 0.3):
    """Name of the loaded terrain region that contains (lat, lon) with margin, else None."""
    for name, (lat_r, lon_r, ddir) in D.REGIONS.items():
        if lat_r[0] + margin_deg <= lat <= lat_r[1] + 1 - margin_deg and lon_r[0] + margin_deg <= lon <= lon_r[1] + 1 - margin_deg:
            if (D.CACHE / f"dem_{name}.npy").exists() or any(pathlib.Path(ddir).glob("*.tif")):
                return name
    return None


def _prof_rows(args):
    lats, lons, name = args
    d = _dem(name)
    return np.stack([d.profile(a, b) for a, b in zip(lats, lons)]).astype(np.float32)


def grid(prior_lat: float, prior_lon: float, key: str | None = None, half_km=25.0, step_km=None, procs: int = 16):
    """Cached candidate profiles around the prior. Parallel over grid rows."""
    step_km = step_km or GRID_STEP_KM
    region = dem_for(prior_lat, prior_lon, 0.0) or "swiss"
    key = (key or f"{prior_lat:.4f}_{prior_lon:.4f}_{int(half_km)}") + ("" if step_km == 1.0 else f"_s{step_km:g}")
    f = D.CACHE / f"grid_{region}_{key}.npz"
    if f.exists():
        z = np.load(f)
        return z["lats"], z["lons"], z["prof"]
    n = int(round(half_km / step_km))
    off = np.arange(-n, n + 1) * step_km
    cl = math.cos(math.radians(prior_lat))
    LA = prior_lat + off[:, None] / 111.195 + 0 * off[None, :]
    LO = prior_lon + 0 * off[:, None] + off[None, :] / (111.195 * cl)
    rows = [(LA[i], LO[i], region) for i in range(len(off))]
    if procs > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(procs) as p:  # spawn: safe from a threaded server with CUDA (SAM) initialised
            prof = np.concatenate(p.map(_prof_rows, rows))
    else:
        prof = np.concatenate([_prof_rows(r) for r in rows])
    lats, lons = LA.ravel(), LO.ravel()
    D.CACHE.mkdir(exist_ok=True)
    np.savez_compressed(f, lats=lats, lons=lons, prof=prof, prior=np.array([prior_lat, prior_lon]), half_km=half_km, step_km=step_km)
    return lats, lons, prof


def photo_horizon(img: Image.Image, focal_px: float, method="auto"):
    rows, used, sky = HZ.extract(img, method)
    W, H = img.size
    az, el = HZ.rows_to_angles(rows, focal_px, W, H)
    valid = (rows > 1) & (rows < H - 2)
    return dict(rows=rows, az=az, el=el, valid=valid, method=used, sky=sky)


def resample_1deg(az, el, valid):
    j = np.arange(math.ceil(az.min()), math.floor(az.max()) + 1)
    e = np.interp(j, az, el)
    v = np.interp(j, az, valid.astype(float)) > 0.99
    return j.astype(int), e, v


def match(j, e, v, prof, score=DEFAULT_SCORE, chunk=1500):
    """Returns per-cell best score (N,), per-cell best heading (N,), full (N,360) score. Chunked over cells."""
    if len(prof) > chunk:
        parts = [_match(j, e, v, prof[i:i + chunk], score) for i in range(0, len(prof), chunk)]
        return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts]), np.concatenate([p[2] for p in parts])
    return _match(j, e, v, prof, score)


def _match(j, e, v, prof, score):
    jj, ee = j[v], e[v]
    if len(jj) < 8:
        raise ValueError("too few valid horizon columns (< 8 deg of skyline)")
    psi = np.arange(360)
    idx = (psi[:, None] + jj[None, :]) % 360  # (360, J)
    W = prof[:, idx]  # (N, 360, J)
    ec = ee - ee.mean()
    Wc = W - W.mean(-1, keepdims=True)
    if score == "ncc":
        num = (Wc * ec).sum(-1)
        den = np.sqrt((Wc ** 2).sum(-1) * (ec ** 2).sum()) + 1e-9
        S = num / den
    elif score == "rms":
        S = -np.sqrt(((Wc - ec) ** 2).mean(-1))
    elif score == "rms_detrend":
        # unknown pitch AND small camera roll: fit offset + linear slope in azimuth, score = -RMS of residual
        xc = (jj - jj.mean()).astype(np.float64)
        Dd = Wc - ec
        b = (Dd * xc).sum(-1, keepdims=True) / (xc ** 2).sum()
        b = np.clip(b, -0.18, 0.18)  # |slope| <= ~10 deg roll equivalent
        S = -np.sqrt(((Dd - b * xc) ** 2).mean(-1))
    else:
        raise ValueError(score)
    best_psi = S.argmax(1)
    return S.max(1), best_psi, S


def ring_from_scores(cell_scores, lats, lons, ibest, top_frac=0.05):
    n = max(1, int(round(top_frac * len(cell_scores))))
    top = np.argsort(-cell_scores)[:n]
    dn = (lats[top] - lats[ibest]) * 111.195
    de = (lons[top] - lons[ibest]) * 111.195 * math.cos(math.radians(lats[ibest]))
    d = np.hypot(dn, de)
    return float(d.max()), float(np.percentile(d, 50)), top


def core_ring(cell_scores, lats, lons, ibest, margin, step_km):
    """Radius of the cells scoring within half the ratio-test margin of the best (min = one grid step).
    Defined a priori (not tuned); coverage is reported on TEST."""
    keep = cell_scores >= cell_scores[ibest] - 0.5 * max(margin, 0.0)
    d = np.hypot((lats[keep] - lats[ibest]) * 111.195, (lons[keep] - lons[ibest]) * 111.195 * math.cos(math.radians(lats[ibest])))
    return float(max(step_km, d.max() if len(d) else 0.0))


def margin_test(cell_scores, lats, lons, ibest, away_km=3.0):
    """Ratio-test style ambiguity: best score minus the best score of any cell > away_km from the best cell.
    Scores are -RMS (deg), so the margin is in degrees of horizon RMS."""
    d = np.hypot((lats - lats[ibest]) * 111.195, (lons - lons[ibest]) * 111.195 * math.cos(math.radians(lats[ibest])))
    far = d > away_km
    second = float(cell_scores[far].max()) if far.any() else float("-inf")
    return float(cell_scores[ibest] - second), float(-cell_scores[ibest])


def solve(image, focal_px: float | None = None, hfov_deg: float | None = None, prior_lat: float | None = None,
          prior_lon: float | None = None, grid_key: str | None = None, score: str = DEFAULT_SCORE, horizon_method="auto",
          procs: int = 16) -> dict:
    t0 = time.time()
    img = image if isinstance(image, Image.Image) else Image.open(image)
    img = img.convert("RGB")
    W, H = img.size
    if focal_px is None:
        if hfov_deg is None:
            return dict(ok=False, solver="skyline", message="Need the lens focal length or horizontal FOV.")
        focal_px = W / 2 / math.tan(math.radians(hfov_deg) / 2)
    if prior_lat is None or prior_lon is None:
        return dict(ok=False, solver="skyline", message="Skyline search needs a last-known fix (prior) to within ~25 km.")
    if dem_for(prior_lat, prior_lon) is None:
        return dict(ok=False, solver="skyline", message="No terrain model loaded for this area (loaded: Swiss Alps test region, Boston/Blue Hills).")
    th = time.time()
    ph = photo_horizon(img, focal_px, horizon_method)
    t_h = time.time() - th
    tg = time.time()
    lats, lons, prof = grid(prior_lat, prior_lon, grid_key, procs=procs)
    t_g = time.time() - tg
    j, e, v = resample_1deg(ph["az"], ph["el"], ph["valid"])
    tm = time.time()
    try:
        cs, cpsi, _ = match(j, e, v, prof, score)
    except ValueError as ex:
        return dict(ok=False, solver="skyline", message=str(ex), horizon_method=ph["method"])
    t_m = time.time() - tm
    ib = int(cs.argmax())
    ring_max, ring_med, top = ring_from_scores(cs, lats, lons, ib)
    margin, rms_best = margin_test(cs, lats, lons, ib)
    rel_margin = margin / max(rms_best, 1e-3)
    confident = rel_margin >= CONF_REL_MARGIN and score in ("rms", "rms_detrend")  # margin rule calibrated for -RMS scores only
    ring_core = core_ring(cs, lats, lons, ib, margin, GRID_STEP_KM)
    # displayed ring for a distinct match: the core ring alone held the truth only 33 % (DEV) / 61 % (TEST) of the time,
    # so we floor it at 5 km (the spec's own metric): 67 % DEV / 83 % TEST of distinct fixes fall inside.
    ring_conf = max(ring_core, CONF_RING_FLOOR_KM)
    n = int(round(math.sqrt(len(lats))))
    out = dict(ok=True, solver="skyline", lat=float(lats[ib]), lon=float(lons[ib]), heading_deg=float(cpsi[ib] % 360),
               score=float(cs[ib]), score_kind=score, ring_km=round(ring_max, 2), ring_median_km=round(ring_med, 2),
               ring_definition="max distance from best cell to the top-5% scoring cells",
               horizon_method=ph["method"], horizon_valid_deg=int(v.sum()), hfov_deg=round(2 * math.degrees(math.atan(W / 2 / focal_px)), 2),
               prior=[prior_lat, prior_lon], grid=dict(n=n, step_km=GRID_STEP_KM, half_km=25.0),
               timing_ms=dict(horizon=round(t_h * 1e3), grid=round(t_g * 1e3), match=round(t_m * 1e3), total=round((time.time() - t0) * 1e3)),
               score_map=np.round(cs.reshape(n, n), 4).tolist(),
               horizon_rows=np.round(ph["rows"][:: max(1, W // 256)], 1).tolist(),
               terrain_profile_at_fix=np.round(prof[ib], 3).tolist(),
               photo_profile=dict(az_offsets=j.tolist(), el=np.round(e, 3).tolist(), valid=v.tolist()))
    out.update(confident=bool(confident), ring_core_km=round(ring_core, 2), ring_conf_km=round(ring_conf, 2), margin_deg=round(margin, 4), rms_deg=round(rms_best, 4), rel_margin=round(rel_margin, 3),
               conf_threshold=CONF_REL_MARGIN)
    if confident:
        out["message"] = (f"Skyline fix (distinct match, margin {rel_margin:.2f}). Ring {ring_conf:.0f} km; the top-5% "
                          f"cells spread {ring_max:.0f} km (dashed). Search box ±25 km around your last fix.")
    else:
        out["message"] = (f"AMBIGUOUS: this skyline matches several places in the ±25 km box (margin {rel_margin:.2f} < "
                          f"{CONF_REL_MARGIN}). Best guess shown with the full ring; keep using your last fix or shoot a wider view.")
    return out


if __name__ == "__main__":
    import json, sys, ch1
    dev, test = ch1.split()
    it = dev[0]
    r = solve(it["path"], it["focal_px"], prior_lat=it["prior_lat"], prior_lon=it["prior_lon"], grid_key=it["loc_key"])
    e = math.hypot((r["lat"] - it["lat"]) * 111.195, (r["lon"] - it["lon"]) * 111.195 * math.cos(math.radians(it["lat"])))
    print({k: r[k] for k in ("lat", "lon", "heading_deg", "score", "ring_km", "ring_median_km", "horizon_method", "timing_ms")}, "err km", round(e, 2))
