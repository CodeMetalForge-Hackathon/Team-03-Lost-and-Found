"""Phase 2 evaluation on CH1. Usage: python eval_skyline.py [dev|test] [rms|ncc] [auto|gt]
  horizon 'auto' = SAM2 (fallback DP) — the real pipeline. 'gt' = oracle GT sky mask (upper bound, reported separately).
Writes results/skyline_<split>_<score>_<horizon>.json (+ _summary.json)."""
import json, math, pathlib, sys, time
from multiprocessing import Pool
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import ch1, horizon as HZ, solver_skyline as SK


def _grid(it):
    SK.grid(it["prior_lat"], it["prior_lon"], it["loc_key"], procs=1)
    return it["loc_key"]


def err_km(a, b, c, d):
    return math.hypot((a - c) * 111.195, (b - d) * 111.195 * math.cos(math.radians(c)))


def main():
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    score = sys.argv[2] if len(sys.argv) > 2 else "rms"
    hz = sys.argv[3] if len(sys.argv) > 3 else "auto"
    dev, test = ch1.split()
    items = dev if split == "dev" else test
    t0 = time.time()
    with Pool(16) as p:
        p.map(_grid, items)
    t_grid = time.time() - t0
    rows = []
    for it in items:
        img = Image.open(it["path"]).convert("RGB")
        gt = HZ.gt_rows(it["mask"])
        th = time.time()
        if hz == "gt":
            hrows, used = gt, "gt_oracle"
        else:
            hrows, used, _ = HZ.extract(img, "auto")
        t_h = time.time() - th
        W, H = img.size
        az, el = HZ.rows_to_angles(hrows, it["focal_px"], W, H)
        valid = (hrows > 1) & (hrows < H - 2)
        j, e, v = SK.resample_1deg(az, el, valid)
        lats, lons, prof = SK.grid(it["prior_lat"], it["prior_lon"], it["loc_key"])
        tm = time.time()
        try:
            cs, cpsi, _ = SK.match(j, e, v, prof, score)
        except ValueError as ex:
            rows.append(dict(id=it["id"], ok=False, error=str(ex)))
            continue
        ib = int(cs.argmax())
        ring, ring_med, _ = SK.ring_from_scores(cs, lats, lons, ib)
        # best achievable on this grid (quantisation floor) and rank of the cell nearest the truth
        d_all = np.hypot((lats - it["lat"]) * 111.195, (lons - it["lon"]) * 111.195 * math.cos(math.radians(it["lat"])))
        inear = int(d_all.argmin())
        rank = int((cs > cs[inear]).sum()) + 1
        e_km = err_km(lats[ib], lons[ib], it["lat"], it["lon"])
        margin, rms_best = SK.margin_test(cs, lats, lons, ib)
        rcore = SK.core_ring(cs, lats, lons, ib, margin, SK.GRID_STEP_KM)
        rows.append(dict(id=it["id"], loc_key=it["loc_key"], ok=True, err_km=round(e_km, 3), ring_core_km=round(rcore, 2), truth_in_core=bool(e_km <= rcore), margin=round(margin, 4), rms_best=round(rms_best, 4), rel_margin=round(margin / max(rms_best, 1e-3), 4), ring_km=round(ring, 2),
                         ring_median_km=round(ring_med, 2), truth_in_ring=bool(e_km <= ring), prior_offset_km=round(it["prior_offset_km"], 2),
                         prior_err_km=round(err_km(it["prior_lat"], it["prior_lon"], it["lat"], it["lon"]), 2),
                         grid_floor_km=round(float(d_all.min()), 3), truth_cell_rank=rank, n_cells=len(cs),
                         heading_deg=int(cpsi[ib]), score=round(float(cs[ib]), 4), horizon_method=used,
                         horizon_mae_px=round(float(np.abs(hrows - gt).mean()), 2), valid_deg=int(v.sum()),
                         hfov=round(it["hfov"], 1), t_horizon_ms=round(t_h * 1e3), t_match_ms=round((time.time() - tm) * 1e3)))
    ok = [r for r in rows if r["ok"]]
    e = np.array([r["err_km"] for r in ok])
    pe = np.array([r["prior_err_km"] for r in ok])
    summ = dict(split=split, score=score, horizon=hz, n=len(rows), n_ok=len(ok),
                median_km=round(float(np.median(e)), 2), p75_km=round(float(np.percentile(e, 75)), 2),
                mean_km=round(float(e.mean()), 2), frac_within_5km=round(float((e <= 5).mean()), 3),
                frac_within_2km=round(float((e <= 2).mean()), 3), frac_better_than_prior=round(float((e < pe).mean()), 3),
                prior_median_km=round(float(np.median(pe)), 2), ring_median_km=round(float(np.median([r["ring_km"] for r in ok])), 2),
                truth_in_ring_frac=round(float(np.mean([r["truth_in_ring"] for r in ok])), 3),
                truth_cell_rank_median=float(np.median([r["truth_cell_rank"] for r in ok])),
                horizon_mae_px_median=round(float(np.median([r["horizon_mae_px"] for r in ok])), 2),
                horizon_methods={m: sum(r["horizon_method"] == m for r in ok) for m in {r["horizon_method"] for r in ok}},
                t_horizon_ms_median=float(np.median([r["t_horizon_ms"] for r in ok])), t_match_ms_median=float(np.median([r["t_match_ms"] for r in ok])),
                t_grid_all_s=round(t_grid, 1))
    for thr in (0.02, 0.05, 0.1, 0.15, 0.2, 0.3):
        c = [r for r in ok if r["rel_margin"] >= thr]
        summ[f"conf_relmargin_{thr}"] = dict(n=len(c), frac=round(len(c) / len(ok), 3),
                                             median_km=round(float(np.median([r["err_km"] for r in c])), 2) if c else None,
                                             within_5km=round(float(np.mean([r["err_km"] <= 5 for r in c])), 3) if c else None,
                                             truth_in_core=round(float(np.mean([r["truth_in_core"] for r in c])), 3) if c else None,
                                             core_median_km=round(float(np.median([r["ring_core_km"] for r in c])), 2) if c else None)
    import solver_skyline as _S
    tag = f"{split}_{score}_{hz}" + ("" if _S.GRID_STEP_KM == 1.0 else f"_s{_S.GRID_STEP_KM:g}")
    (ROOT / "results" / f"skyline_{tag}.json").write_text(json.dumps(rows, indent=1))
    (ROOT / "results" / f"skyline_{tag}_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ))


if __name__ == "__main__":
    main()
