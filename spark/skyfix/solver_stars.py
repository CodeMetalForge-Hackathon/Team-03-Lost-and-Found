"""Sky Fix star solver: phone night-sky photo (+ UTC + optional gravity vector) -> sky orientation -> lat/lon/heading.

Pipeline
1. Centroids: tetra3.get_centroids_from_image.
2. Plate solve: phone-FOV database (20-70 deg); on failure centre-crop to ~30 deg and use tetra3's shipped
   default database (10-30 deg); on failure sweep fov_estimate 50/60/70/80 deg on the phone database.
3. Orientation: Kabsch fit of matched pixel rays (camera frame x=right, y=down, z=out of lens) to the matched
   catalogue unit vectors (ICRS) -> rotation R_cam->ICRS. Residual RMS = centroid_rms_deg.
4. With a gravity vector (direction of DOWN in the camera frame):
   zenith_ICRS = R @ (-g)   ->  apparent (TETE, of date) RA/Dec  ->  lat = Dec, lon = RA - GAST(UTC)  [first pass]
   then 2 Gauss-Newton refinements in the local horizon frame with atmospheric refraction applied to the matched
   stars (refraction lifts low stars, which would otherwise bias the fix by a few km).
   heading = azimuth of the camera's forward axis. ring_km = 111 * (centroid_rms_deg + tilt_sigma_deg).
5. Without a gravity vector: sky orientation only. No latitude without the phone's gravity vector.
"""
from __future__ import annotations
import io, pathlib, time, logging, math
from datetime import datetime, timezone
import numpy as np
from PIL import Image, ImageOps

logging.getLogger("tetra3").setLevel(logging.WARNING)
if not hasattr(np, "math"):  # tetra3 uses np.math (removed in numpy 2.x); shim, do not patch tetra3
    np.math = math
ROOT = pathlib.Path(__file__).resolve().parent
PHONE_DB = ROOT / "data" / "stars" / "phone_fov70_db.npz"
TILT_SIGMA = {"braced": 0.3, "handheld": 1.4}  # deg, Grm & Grm 2021 (phone accelerometer tilt error)
KM_PER_DEG = 111.2
MAX_SIDE = 2400  # downscale larger photos (area resampling keeps star flux)

_T3 = {}


def _t3(which: str):
    import tetra3
    if which not in _T3:
        if which == "phone":
            _T3[which] = tetra3.Tetra3(load_database=str(PHONE_DB))
        else:
            _T3[which] = tetra3.Tetra3()  # shipped default_database.npz (10-30 deg)
    return _T3[which]


def _iers_offline():
    from astropy.utils import iers
    iers.conf.auto_download = False
    iers.conf.auto_max_age = None
    iers.conf.iers_degraded_accuracy = "warn"


def load_gray(image) -> np.ndarray:
    if isinstance(image, (bytes, bytearray)):
        im = Image.open(io.BytesIO(image))
    elif isinstance(image, Image.Image):
        im = image
    else:
        im = Image.open(image)
    im = ImageOps.exif_transpose(im).convert("L")
    s = max(im.size) / MAX_SIDE
    if s > 1:
        im = im.resize((round(im.size[0] / s), round(im.size[1] / s)), Image.BOX)
    return np.asarray(im, dtype=np.float32)


def exif_utc(image, tz_offset_min: int | None = None) -> str | None:
    """UTC from EXIF DateTimeOriginal + OffsetTimeOriginal. Without an EXIF offset, uses tz_offset_min (the phone's
    current UTC offset, minutes east) if given; otherwise None (timezone unknown)."""
    import exifread
    f = io.BytesIO(image) if isinstance(image, (bytes, bytearray)) else open(image, "rb")
    with f:
        tags = exifread.process_file(f, details=False)
    dto, off = tags.get("EXIF DateTimeOriginal"), tags.get("EXIF OffsetTimeOriginal")
    if not dto:
        return None
    if not off:
        if tz_offset_min is None:
            return None
        sign = "+" if tz_offset_min >= 0 else "-"
        off = f"{sign}{abs(tz_offset_min) // 60:02d}:{abs(tz_offset_min) % 60:02d}"
    dt = datetime.strptime(f"{dto} {str(off).replace(':', '')}", "%Y:%m:%d %H:%M:%S %z")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def fov_from_f35(f35: float, width: int, height: int) -> float:
    """Horizontal FOV (deg, across the image width as displayed) from the EXIF 35 mm-equivalent focal length.
    35 mm equivalence is defined on the 43.27 mm full-frame diagonal, so aspect ratio and orientation matter."""
    half_w = 43.27 / 2 * width / math.hypot(width, height)
    return math.degrees(2 * math.atan(half_w / f35))


def exif_fov(image, width: int, height: int) -> float | None:
    import exifread
    f = io.BytesIO(image) if isinstance(image, (bytes, bytearray)) else open(image, "rb")
    with f:
        tags = exifread.process_file(f, details=False)
    t = tags.get("EXIF FocalLengthIn35mmFilm")
    try:
        f35 = float(str(t)) if t else 0
    except ValueError:
        f35 = 0
    return fov_from_f35(f35, width, height) if f35 > 0 else None


def radec_to_vec(ra, dec):
    ra, dec = np.deg2rad(ra), np.deg2rad(dec)
    return np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)], -1)


def vec_to_radec(v):
    v = np.asarray(v) / np.linalg.norm(v)
    return float(np.rad2deg(np.arctan2(v[1], v[0])) % 360), float(np.rad2deg(np.arcsin(np.clip(v[2], -1, 1))))


def pix_to_cam(yx, size, fov_deg):
    """tetra3 centroids (y,x), pixel-edge origin -> unit rays in camera frame (x right, y down, z forward)."""
    h, w = size
    f = (w / 2) / math.tan(math.radians(fov_deg) / 2)
    yx = np.asarray(yx, dtype=np.float64)
    v = np.stack([(yx[:, 1] - w / 2) / f, (yx[:, 0] - h / 2) / f, np.ones(len(yx))], 1)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def kabsch(a, b):
    """Rotation R minimising |R a_i - b_i|. Returns R, rms angle (deg)."""
    H = a.T @ b
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    res = np.rad2deg(np.arccos(np.clip(np.sum((a @ R.T) * b, 1), -1, 1)))
    return R, float(np.sqrt(np.mean(res ** 2)))


def plate_solve(img: np.ndarray, fov_estimate: float | None = None, solve_timeout_ms: int = 4000):
    """Returns (solution dict or None, attempts list). Solution has rotation in full-image camera frame."""
    import tetra3
    h, w = img.shape
    attempts = []
    t0 = time.time()
    cents = tetra3.get_centroids_from_image(img, max_returned=60)
    n_cent = len(cents)

    def finish(sol, cents_used, size, offset, method):
        if sol is None or sol.get("RA") is None:
            return None
        yx = np.asarray(sol["matched_centroids"], dtype=np.float64) + np.asarray(offset)[None]
        stars = np.asarray(sol["matched_stars"], dtype=np.float64)
        cam = pix_to_cam(yx, (h, w), _full_fov(sol["FOV"], size, (h, w)))
        cat = radec_to_vec(stars[:, 0], stars[:, 1])
        R, rms = kabsch(cam, cat)
        return dict(method=method, ra=float(sol["RA"]), dec=float(sol["Dec"]), roll=float(sol["Roll"]),
                    fov=_full_fov(sol["FOV"], size, (h, w)), matches=int(sol["Matches"]), rmse_arcsec=float(sol["RMSE"]),
                    prob=float(sol["Prob"]), t_solve_ms=float(sol["T_solve"]), R=R, centroid_rms_deg=rms,
                    matched_cam=cam, matched_cat=cat, matched_mag=stars[:, 2], n_centroids=n_cent)

    if n_cent >= 4:
        # 1. phone database, full frame
        # phone main cameras are 55-80 deg HFOV; with no estimate assume 70 +/- 12
        kw = dict(fov_estimate=fov_estimate or 70.0, fov_max_error=12)
        sol = _t3("phone").solve_from_centroids(cents, (h, w), return_matches=True, solve_timeout=solve_timeout_ms,
                                                pattern_checking_stars=12, **kw)
        attempts.append({"method": "phone_db_full", "ok": sol.get("RA") is not None, "fov_estimate": kw["fov_estimate"]})
        out = finish(sol, cents, (h, w), (0, 0), "phone_db_full")
        if out:
            return out | {"total_ms": (time.time() - t0) * 1e3}, attempts
    # 2. centre crop ~30 deg, shipped default database
    fe = fov_estimate or 70.0
    frac = min(1.0, math.tan(math.radians(15)) / math.tan(math.radians(fe / 2)))
    cw, ch = int(w * frac), int(h * frac)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    crop = img[y0:y0 + ch, x0:x0 + cw]
    cc = tetra3.get_centroids_from_image(crop, max_returned=40)
    if len(cc) >= 4:
        crop_fov = 2 * math.degrees(math.atan(math.tan(math.radians(fe / 2)) * frac))
        sol = _t3("default").solve_from_centroids(cc, (ch, cw), fov_estimate=crop_fov, fov_max_error=8,
                                                  return_matches=True, solve_timeout=solve_timeout_ms)
        attempts.append({"method": "default_db_centre_crop", "ok": sol.get("RA") is not None, "crop_fov": round(crop_fov, 1)})
        out = finish(sol, cc, (ch, cw), (y0, x0), "default_db_centre_crop")
        if out:
            return out | {"total_ms": (time.time() - t0) * 1e3}, attempts
    # 2b. sky-only: keep centroids in the upper half of the frame (foreground trees/lights live at the bottom)
    if n_cent >= 4:
        allc = tetra3.get_centroids_from_image(img, max_returned=400)
        up = allc[allc[:, 0] < 0.5 * h][:60] if len(allc) else allc
        if len(up) >= 4:
            sol = _t3("phone").solve_from_centroids(up, (h, w), fov_estimate=fe, fov_max_error=12, pattern_checking_stars=12,
                                                    return_matches=True, solve_timeout=solve_timeout_ms)
            attempts.append({"method": "phone_db_upper_half", "ok": sol.get("RA") is not None})
            out = finish(sol, up, (h, w), (0, 0), "phone_db_upper_half")
            if out:
                return out | {"total_ms": (time.time() - t0) * 1e3}, attempts
    # 3. FOV sweep on phone DB
    if n_cent >= 4:
        for fe2 in (50, 60, 70, 80):
            sol = _t3("phone").solve_from_centroids(cents, (h, w), fov_estimate=fe2, fov_max_error=6, pattern_checking_stars=12,
                                                    return_matches=True, solve_timeout=solve_timeout_ms // 2)
            attempts.append({"method": f"phone_db_fov{fe2}", "ok": sol.get("RA") is not None})
            out = finish(sol, cents, (h, w), (0, 0), f"phone_db_fov{fe2}")
            if out:
                return out | {"total_ms": (time.time() - t0) * 1e3}, attempts
        # 4. blind (no FOV prior) on phone DB
        sol = _t3("phone").solve_from_centroids(cents, (h, w), pattern_checking_stars=12, return_matches=True,
                                                solve_timeout=solve_timeout_ms)
        attempts.append({"method": "phone_db_blind", "ok": sol.get("RA") is not None})
        out = finish(sol, cents, (h, w), (0, 0), "phone_db_blind")
        if out:
            return out | {"total_ms": (time.time() - t0) * 1e3}, attempts
    return None, attempts + [{"n_centroids": n_cent, "total_ms": (time.time() - t0) * 1e3}]


def _full_fov(fov_sub, size_sub, size_full):
    """Convert a horizontal FOV solved on a (centred) sub-image into the full-image horizontal FOV."""
    ws, wf = size_sub[1], size_full[1]
    if ws == wf:
        return float(fov_sub)
    return float(2 * math.degrees(math.atan(math.tan(math.radians(fov_sub) / 2) * wf / ws)))


def _local_enu_matrix(lat, lon):
    """Rows: East, North, Up unit vectors in an Earth-fixed frame where lon is measured from the x axis."""
    la, lo = math.radians(lat), math.radians(lon)
    e = np.array([-math.sin(lo), math.cos(lo), 0.0])
    n = np.array([-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)])
    u = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    return np.stack([e, n, u])


def locate(sol: dict, utc: str, gravity_cam, elevation_m: float = 0.0, refine: bool = True):
    """Gravity-aided fix. gravity_cam = direction of DOWN in the camera frame (any magnitude)."""
    _iers_offline()
    from astropy.coordinates import SkyCoord, TETE, AltAz, EarthLocation
    from astropy.time import Time
    import astropy.units as u
    t = Time(utc, scale="utc")
    g = np.asarray(gravity_cam, dtype=np.float64)
    zen_cam = -g / np.linalg.norm(g)
    R = sol["R"]
    zen_icrs = R @ zen_cam
    ra_z, dec_z = vec_to_radec(zen_icrs)
    app = SkyCoord(ra=ra_z * u.deg, dec=dec_z * u.deg, frame="icrs").transform_to(TETE(obstime=t))
    gast = t.sidereal_time("apparent", "greenwich").deg
    lat0 = float(app.dec.deg)
    lon0 = float((app.ra.deg - gast + 180) % 360 - 180)
    lat, lon = lat0, lon0
    iters = []
    if refine:
        cat = SkyCoord(ra=np.rad2deg(np.arctan2(sol["matched_cat"][:, 1], sol["matched_cat"][:, 0])) * u.deg,
                       dec=np.rad2deg(np.arcsin(sol["matched_cat"][:, 2])) * u.deg, frame="icrs")
        for _ in range(3):
            loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elevation_m * u.m)
            aa = cat.transform_to(AltAz(obstime=t, location=loc, pressure=1010 * u.hPa * math.exp(-elevation_m / 8400),
                                        temperature=5 * u.deg_C, relative_humidity=0.5, obswl=0.55 * u.micron))
            alt, az = aa.alt.rad, aa.az.rad
            enu = np.stack([np.sin(az) * np.cos(alt), np.cos(az) * np.cos(alt), np.sin(alt)], 1)
            Rl, rms_l = kabsch(sol["matched_cam"], enu)  # camera -> local ENU at the current guess
            z = Rl @ zen_cam  # measured zenith expressed in the guessed local frame
            dN, dE = math.degrees(math.asin(z[1])), math.degrees(math.asin(z[0]))
            lat += dN
            lon = (lon + dE / max(0.05, math.cos(math.radians(lat))) + 180) % 360 - 180
            iters.append(dict(dN_km=dN * KM_PER_DEG, dE_km=dE * KM_PER_DEG * math.cos(math.radians(lat)), rms_deg=rms_l))
            if abs(dN) < 1e-5 and abs(dE) < 1e-5:
                break
        fwd = Rl @ np.array([0, 0, 1.0])
        right = Rl @ np.array([1.0, 0, 0])
    else:
        Rl = _local_enu_matrix(lat, lon)  # crude fallback (unused by default)
        fwd = right = np.array([0, 1.0, 0])
    heading = float(math.degrees(math.atan2(fwd[0], fwd[1])) % 360)
    cam_alt = float(math.degrees(math.asin(np.clip(fwd[2], -1, 1))))
    return dict(lat=lat, lon=lon, lat_first_pass=lat0, lon_first_pass=lon0, heading_deg=heading,
                camera_alt_deg=cam_alt, zenith_ra=ra_z, zenith_dec=dec_z, gast_deg=float(gast), refine_iters=iters)


def solve(image, utc: str | None = None, gravity=None, fov_estimate: float | None = None,
          tilt: str | float = "braced", elevation_m: float = 0.0) -> dict:
    t0 = time.time()
    img = load_gray(image)
    if utc is None and not isinstance(image, np.ndarray):
        try:
            utc = exif_utc(image)
        except Exception:
            utc = None
    fov_src = "request" if fov_estimate else None
    if fov_estimate is None and not isinstance(image, np.ndarray):
        try:
            fov_estimate = exif_fov(image, img.shape[1], img.shape[0])
            fov_src = "exif_f35" if fov_estimate else None
        except Exception:
            fov_estimate = None
    sol, attempts = plate_solve(img, fov_estimate)
    out = {"solver": "stars", "fov_estimate": fov_estimate, "fov_estimate_source": fov_src, "image_size": [int(img.shape[1]), int(img.shape[0])], "attempts": attempts, "utc": utc}
    if sol is None:
        out.update(ok=False, message="No plate solution: too few stars detected or no pattern match. "
                                     "Try a longer exposure, brace the phone, or point higher.",
                   total_ms=round((time.time() - t0) * 1e3, 1))
        return out
    out.update(ok=True, sky={k: (round(sol[k], 4) if isinstance(sol[k], float) else sol[k])
                             for k in ("method", "ra", "dec", "roll", "fov", "matches", "rmse_arcsec", "prob",
                                       "t_solve_ms", "centroid_rms_deg", "n_centroids")})
    if gravity is None:
        out.update(fix=None, message="Sky orientation solved. No latitude without the phone's gravity vector — not guessing.")
    elif utc is None:
        out.update(fix=None, message="Sky orientation solved, but no UTC time: longitude needs the clock. Not guessing.")
    else:
        tilt_sigma = float(TILT_SIGMA.get(tilt, tilt)) if not isinstance(tilt, (int, float)) else float(tilt)
        fx = locate(sol, utc, gravity, elevation_m)
        ring_km = KM_PER_DEG * (sol["centroid_rms_deg"] + tilt_sigma)
        # tilt error has two independent axes (Rayleigh radius): the spec ring (1 sigma) holds the truth only ~39 % of
        # the time; 2.45 sigma holds 95 %. Both are reported; the app draws both.
        ring95_km = KM_PER_DEG * (sol["centroid_rms_deg"] + 2.45 * tilt_sigma)
        fx.update(ring_km=round(ring_km, 2), ring95_km=round(ring95_km, 2), tilt_sigma_deg=tilt_sigma,
                  ring_formula="111 km x (centroid_rms_deg + tilt_sigma_deg); ring95 uses 2.45 x tilt_sigma")
        out.update(fix=fx, message=f"Fix from {sol['matches']} stars; ring {ring_km:.0f} km (1σ) / {ring95_km:.0f} km (95%), set by the phone tilt sensor, not the stars.")
    out["total_ms"] = round((time.time() - t0) * 1e3, 1)
    return out


if __name__ == "__main__":
    import sys, json
    p = sys.argv[1]
    meta = pathlib.Path(p).with_suffix(".json")
    kw = {}
    if meta.exists():
        m = json.loads(meta.read_text())
        kw = dict(utc=m["utc"].rstrip("Z"), gravity=m["gravity_cam"])
    r = solve(p, **kw)
    print(json.dumps(r, indent=1, default=str))
    if meta.exists() and r.get("fix"):
        from math import radians, cos
        dn = (r["fix"]["lat"] - m["lat"]) * KM_PER_DEG
        de = (r["fix"]["lon"] - m["lon"]) * KM_PER_DEG * cos(radians(m["lat"]))
        print("error km", round((dn ** 2 + de ** 2) ** .5, 3), "heading err", round((r["fix"]["heading_deg"] - m["az"] + 180) % 360 - 180, 3))
