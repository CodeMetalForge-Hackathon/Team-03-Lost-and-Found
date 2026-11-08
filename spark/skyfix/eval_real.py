"""Phase 1 real photos: sky-orientation solve rate on AstroSmartphoneDataset (EXIF-timed subset) and the
Wikimedia geotagged set. Real photos carry no gravity vector, so NO position is computed from them.
Annotation only (uses the photo's own GPS + time, never fed to the solver): altitude/azimuth of the solved
image centre at the true place/time, and whether the astronomical horizon falls inside the frame.
Writes results/stars_real.json and results/stars_real_summary.json."""
import json, math, pathlib, sys, time
from multiprocessing import Pool
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def items():
    out = []
    for r in json.loads((ROOT / "data/stars/astrosmartphone/index.json").read_text()):
        f35 = r.get("focal_35mm")
        out.append(dict(set="astrosmartphone", subset=r["subset"], path=str(ROOT / r["file"]), lat=r["lat"], lon=r["lon"],
                        dto=r["datetime_original"], offset=r["offset_time"],
                        fov_est=(2 * math.degrees(math.atan(18 / f35)) if f35 else None)))
    for w in json.loads((ROOT / "data/sky_photos/index_enriched.json").read_text()):
        f35 = w.get("exif_focal_35mm")
        out.append(dict(set="wikimedia", subset="wikimedia", path=str(ROOT / "data/sky_photos" / w["file"]), lat=w["lat"],
                        lon=w["lon"], dto=w.get("exif_datetime") or w.get("datetime_original"), offset=None,
                        fov_est=(2 * math.degrees(math.atan(18 / f35)) if f35 else None), title=w.get("title")))
    return out


def run(it):
    import solver_stars as S
    t0 = time.time()
    try:
        img = S.load_gray(it["path"])
        it = dict(it, fov_est=S.exif_fov(it["path"], img.shape[1], img.shape[0]))
        sol, att = S.plate_solve(img, it["fov_est"])
    except Exception as e:
        return dict(it, solved=False, error=repr(e))
    row = dict(it, solved=sol is not None, ms=round((time.time() - t0) * 1e3, 1), attempts=[a.get("method") for a in att if "method" in a])
    try:
        row["utc"] = S.exif_utc(it["path"])
    except Exception:
        row["utc"] = None
    if sol:
        row.update(method=sol["method"], ra=sol["ra"], dec=sol["dec"], roll=sol["roll"], fov=sol["fov"], matches=sol["matches"],
                   rms_deg=sol["centroid_rms_deg"], prob=sol["prob"], n_centroids=sol["n_centroids"])
        if row["utc"] and it["lat"] is not None:
            from astropy.coordinates import SkyCoord, AltAz, EarthLocation
            from astropy.time import Time
            import astropy.units as u
            S._iers_offline()
            loc = EarthLocation(lat=it["lat"] * u.deg, lon=it["lon"] * u.deg)
            fr = AltAz(obstime=Time(row["utc"]), location=loc)
            c = SkyCoord(ra=sol["ra"] * u.deg, dec=sol["dec"] * u.deg).transform_to(fr)
            row["centre_alt_at_truth"] = round(float(c.alt.deg), 2)
            row["centre_az_at_truth"] = round(float(c.az.deg), 2)
            vfov = 2 * math.degrees(math.atan(math.tan(math.radians(sol["fov"] / 2)) * img.shape[0] / img.shape[1]))
            row["horizon_in_frame_predicted"] = bool(c.alt.deg - vfov / 2 < 0)
    return row


def main():
    its = items()
    with Pool(12) as p:
        rows = p.map(run, its, chunksize=2)
    (ROOT / "results/stars_real.json").write_text(json.dumps(rows, indent=1, default=str))
    summ = {}
    for key in sorted({r["subset"] for r in rows}):
        rr = [r for r in rows if r["subset"] == key]
        ok = [r for r in rr if r["solved"]]
        chk = [r for r in ok if "centre_alt_at_truth" in r]
        summ[key] = dict(n=len(rr), solved=len(ok), rate=round(len(ok) / len(rr), 3),
                         with_utc_offset=sum(bool(r.get("utc")) for r in rr),
                         solved_with_gps_and_utc=len(chk),
                         centre_above_horizon_at_truth=sum(r["centre_alt_at_truth"] > 0 for r in chk),
                         horizon_in_frame_predicted=sum(r["horizon_in_frame_predicted"] for r in chk),
                         solved_with_exif_fov=sum(bool(r.get("fov_est")) for r in ok),
                         solved_fov_within_3pct_of_exif=sum(bool(r.get("fov_est")) and abs(r["fov"] / r["fov_est"] - 1) < 0.03 for r in ok),
                         median_prob=float(np.median([r["prob"] for r in ok])) if ok else None,
                         median_ms=round(float(np.median([r["ms"] for r in rr if "ms" in r])), 1) if rr else None,
                         methods={m: sum(r.get("method") == m for r in ok) for m in sorted({r.get("method") for r in ok})})
    allr = [r for r in rows]
    summ["ALL"] = dict(n=len(allr), solved=sum(r["solved"] for r in allr), rate=round(sum(r["solved"] for r in allr) / len(allr), 3))
    (ROOT / "results/stars_real_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
