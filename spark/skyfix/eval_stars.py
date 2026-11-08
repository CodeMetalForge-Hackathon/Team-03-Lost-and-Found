"""Phase 1 acceptance: star solver on the 60 synthetic frames.
Plate-solve each frame once, then locate with the exact gravity vector and with tilt noise
(each of the two tilt components ~ N(0, sigma), sigma in {0.1, 0.3, 1.4} deg, 3 seeded draws each).
Writes results/stars_synth.json and results/stars_synth_summary.json. Re-run: python eval_stars.py"""
import json, math, pathlib, sys, time, zlib
from multiprocessing import Pool
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
FR = ROOT / "synth" / "frames"
SIGMAS = [0.0, 0.1, 0.3, 1.4]
DRAWS = 3


def err_km(lat, lon, tlat, tlon):
    dn = (lat - tlat) * 111.2
    de = ((lon - tlon + 180) % 360 - 180) * 111.2 * math.cos(math.radians(tlat))
    return math.hypot(dn, de)


def tilt(g, sigma_deg, rng):
    g = np.asarray(g, float); g /= np.linalg.norm(g)
    a = np.cross(g, [1.0, 0, 0]);
    if np.linalg.norm(a) < 0.1: a = np.cross(g, [0, 1.0, 0])
    a /= np.linalg.norm(a); b = np.cross(g, a)
    tx, ty = np.deg2rad(rng.normal(0, sigma_deg, 2))
    v = g + tx * a + ty * b
    return (v / np.linalg.norm(v)).tolist(), math.degrees(math.hypot(tx, ty))


def run(png):
    import solver_stars as S
    m = json.loads(png.with_suffix(".json").read_text())
    utc = m["utc"].rstrip("Z")
    t0 = time.time()
    img = S.load_gray(str(png))
    sol, attempts = S.plate_solve(img, None)
    solve_ms = (time.time() - t0) * 1e3
    row = dict(file=png.name, site=m["site"], az=m["az"], alt=m["alt"], solved=sol is not None, solve_ms=round(solve_ms, 1),
               method=sol["method"] if sol else None, matches=sol["matches"] if sol else 0,
               centroid_rms_deg=sol["centroid_rms_deg"] if sol else None, runs=[])
    if not sol:
        return row
    rng = np.random.default_rng(zlib.crc32(png.name.encode()))
    for s in SIGMAS:
        for k in range(1 if s == 0 else DRAWS):
            g, tilt_deg = (m["gravity_cam"], 0.0) if s == 0 else tilt(m["gravity_cam"], s, rng)
            fx = S.locate(sol, utc, g, m["elevation_m"])
            ring1 = S.KM_PER_DEG * (sol["centroid_rms_deg"] + S.TILT_SIGMA["braced"])
            ring95 = S.KM_PER_DEG * (sol["centroid_rms_deg"] + 2.45 * S.TILT_SIGMA["braced"])
            row["runs"].append(dict(sigma=s, draw=k, tilt_applied_deg=round(tilt_deg, 4),
                                    err_km=round(err_km(fx["lat"], fx["lon"], m["lat"], m["lon"]), 3),
                                    err_first_pass_km=round(err_km(fx["lat_first_pass"], fx["lon_first_pass"], m["lat"], m["lon"]), 3),
                                    heading_err_deg=round((fx["heading_deg"] - m["az"] + 180) % 360 - 180, 3), ring1_km=round(ring1, 2), ring95_km=round(ring95, 2)))
    return row


def main():
    pngs = sorted(FR.glob("*.png"))
    with Pool(10) as p:
        rows = p.map(run, pngs)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/stars_synth.json").write_text(json.dumps(rows, indent=1))
    solved = [r for r in rows if r["solved"]]
    summ = {"frames": len(rows), "solved": len(solved), "solve_rate": round(len(solved) / len(rows), 3),
            "solve_ms_median": round(float(np.median([r["solve_ms"] for r in solved])), 1) if solved else None,
            "solve_ms_max": round(float(np.max([r["solve_ms"] for r in solved])), 1) if solved else None,
            "methods": {m: sum(r["method"] == m for r in solved) for m in sorted({r["method"] for r in solved})},
            "matches_median": float(np.median([r["matches"] for r in solved])),
            "centroid_rms_deg_median": round(float(np.median([r["centroid_rms_deg"] for r in solved])), 4),
            "by_sigma": {}}
    for s in SIGMAS:
        e = np.array([x["err_km"] for r in solved for x in r["runs"] if x["sigma"] == s])
        e1 = np.array([x["err_first_pass_km"] for r in solved for x in r["runs"] if x["sigma"] == s])
        h = np.abs([x["heading_err_deg"] for r in solved for x in r["runs"] if x["sigma"] == s])
        ta = np.array([x["tilt_applied_deg"] for r in solved for x in r["runs"] if x["sigma"] == s])
        summ["by_sigma"][str(s)] = dict(n=int(len(e)), median_km=round(float(np.median(e)), 2), p75_km=round(float(np.percentile(e, 75)), 2),
                                        p95_km=round(float(np.percentile(e, 95)), 2), max_km=round(float(e.max()), 2),
                                        frac_within_20km=round(float((e <= 20).mean()), 3),
                                        median_first_pass_km=round(float(np.median(e1)), 2),
                                        in_ring1_braced=round(float(np.mean([x["err_km"] <= x["ring1_km"] for r in solved for x in r["runs"] if x["sigma"] == s])), 3),
                                        in_ring95_braced=round(float(np.mean([x["err_km"] <= x["ring95_km"] for r in solved for x in r["runs"] if x["sigma"] == s])), 3),
                                        median_tilt_applied_deg=round(float(np.median(ta)), 3),
                                        median_heading_err_deg=round(float(np.median(h)), 3), p95_heading_err_deg=round(float(np.percentile(h, 95)), 3))
    (ROOT / "results/stars_synth_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
