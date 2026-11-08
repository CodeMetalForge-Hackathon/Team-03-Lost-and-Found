"""Synthetic phone night-sky renderer with exact ground truth.

Hipparcos (hip_main.dat) -> proper motion to epoch -> astropy AltAz (with refraction) -> pinhole camera
-> Gaussian PSF (atmospheric extinction applied) + sky-glow gradient + Poisson/read noise + optional random
star dropouts (imitates phone noise reduction eating faint stars). Writes PNG + JSON sidecar with every
parameter, including the exact gravity vector in the camera frame.

Camera frame convention (used by solver_stars.py too): x = image right, y = image down, z = out of the lens.
`gravity_cam` is the unit vector pointing DOWN (toward the Earth's centre) expressed in that frame.

CLI:  python synth/render_sky.py --lat 42.36 --lon -71.06 --utc 2026-11-08T05:00:00 --az 30 --alt 35 --out x.png
"""
from __future__ import annotations
import argparse, json, pathlib, sys
from functools import lru_cache
import numpy as np
from PIL import Image

HIP = pathlib.Path(__file__).resolve().parents[1] / "data" / "stars" / "hip_main.dat"


@lru_cache(maxsize=1)
def load_hipparcos(max_mag: float = 7.0):
    """Return arrays (ra_deg, dec_deg, vmag, pmra_masyr, pmdec_masyr, hip) for stars brighter than max_mag.
    Positions are ICRS at epoch J1991.25 (Hipparcos catalogue epoch)."""
    ra, de, vm, pa, pd, hid = [], [], [], [], [], []
    with open(HIP, "r", errors="ignore") as f:
        for line in f:
            p = line.split("|")
            try:
                v = float(p[5]); r = float(p[8]); d = float(p[9])
            except (ValueError, IndexError):
                continue
            if v > max_mag:
                continue
            try:
                a = float(p[12]); b = float(p[13])
            except ValueError:
                a = b = 0.0
            ra.append(r); de.append(d); vm.append(v); pa.append(a); pd.append(b); hid.append(int(p[1]))
    return tuple(np.array(x) for x in (ra, de, vm, pa, pd, hid))


def stars_at_epoch(year: float, max_mag: float = 7.0):
    ra, de, vm, pa, pd, hid = load_hipparcos(max_mag)
    dt = year - 1991.25
    dec = de + pd * dt / 3.6e6
    rra = ra + pa * dt / 3.6e6 / np.cos(np.deg2rad(de))  # pmRA in Hipparcos is mu_alpha* (already x cos dec)
    return rra % 360, dec, vm, hid


def camera_axes(az_deg: float, alt_deg: float, roll_deg: float):
    """Camera right/down/forward unit vectors in local ENU. Positive roll turns the image clockwise."""
    az, alt, rl = np.deg2rad([az_deg, alt_deg, roll_deg])
    f = np.array([np.sin(az) * np.cos(alt), np.cos(az) * np.cos(alt), np.sin(alt)])
    r = np.cross(f, [0.0, 0.0, 1.0]); r /= np.linalg.norm(r)
    d = np.cross(f, r)
    r2 = np.cos(rl) * r + np.sin(rl) * d
    d2 = -np.sin(rl) * r + np.cos(rl) * d
    return r2, d2, f


def render(lat, lon, utc, az, alt, roll=0.0, hfov=70.0, width=2000, height=1500, elevation_m=0.0,
           seed=0, dropout=0.03, psf_sigma=1.3, bg_e=400.0, glow_e=900.0, mag6_peak_snr=3.0,
           read_noise_e=3.0, extinction_k=0.2, refraction=True, max_mag=7.0):
    from astropy.coordinates import SkyCoord, AltAz, EarthLocation
    from astropy.time import Time
    import astropy.units as u

    rng = np.random.default_rng(seed)
    t = Time(utc, scale="utc")
    ra, dec, vm, hid = stars_at_epoch(t.decimalyear, max_mag)
    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elevation_m * u.m)
    kw = dict(obstime=t, location=loc)
    if refraction:
        kw.update(pressure=1010 * u.hPa * np.exp(-elevation_m / 8400), temperature=5 * u.deg_C,
                  relative_humidity=0.5, obswl=0.55 * u.micron)
    aa = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs").transform_to(AltAz(**kw))
    salt, saz = aa.alt.rad, aa.az.rad
    enu = np.stack([np.sin(saz) * np.cos(salt), np.cos(saz) * np.cos(salt), np.sin(salt)], 1)

    r, d, f = camera_axes(az, alt, roll)
    x, y, z = enu @ r, enu @ d, enu @ f
    fpx = (width / 2) / np.tan(np.deg2rad(hfov) / 2)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    ok = (z > 0.05) & (salt > 0)
    u_, v_ = cx + fpx * x / np.where(ok, z, 1), cy + fpx * y / np.where(ok, z, 1)
    ok &= (u_ > -5) & (u_ < width + 5) & (v_ > -5) & (v_ < height + 5)

    # extinction: airmass (Kasten & Young 1989)
    alt_deg = np.rad2deg(salt)
    X = 1.0 / (np.sin(salt) + 0.50572 * (np.clip(alt_deg, 0, 90) + 6.07995) ** -1.6364)
    m_obs = vm + extinction_k * X
    keep = ok.copy()
    n_drop = 0
    if dropout > 0:
        dropmask = rng.random(len(vm)) < dropout
        n_drop = int((keep & dropmask).sum())
        keep &= ~dropmask

    # per-pixel altitude for sky glow and ground
    uu, vv = np.meshgrid(np.arange(width), np.arange(height))
    dirs = (r[None, None] * ((uu - cx) / fpx)[..., None] + d[None, None] * ((vv - cy) / fpx)[..., None] + f[None, None])
    pix_alt = np.rad2deg(np.arcsin(dirs[..., 2] / np.linalg.norm(dirs, axis=-1)))
    img = bg_e + glow_e * np.exp(-np.clip(pix_alt, 0, 90) / 12.0)

    peak6 = mag6_peak_snr * np.sqrt(bg_e)
    total6 = peak6 * 2 * np.pi * psf_sigma ** 2
    flux = total6 * 10 ** (-0.4 * (m_obs - 6.0))
    rad = int(np.ceil(4 * psf_sigma)) + 2
    for i in np.flatnonzero(keep):
        uc, vc = u_[i], v_[i]
        r_ = rad + int(min(6, max(0, (4.5 - m_obs[i])) * 2))
        x0, x1 = max(0, int(uc) - r_), min(width, int(uc) + r_ + 1)
        y0, y1 = max(0, int(vc) - r_), min(height, int(vc) + r_ + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        gx = np.exp(-0.5 * ((np.arange(x0, x1) - uc) / psf_sigma) ** 2)
        gy = np.exp(-0.5 * ((np.arange(y0, y1) - vc) / psf_sigma) ** 2)
        img[y0:y1, x0:x1] += flux[i] / (2 * np.pi * psf_sigma ** 2) * np.outer(gy, gx)

    ground = pix_alt < 0
    img[ground] = bg_e * 0.3
    img = rng.poisson(np.clip(img, 0, None)).astype(np.float64) + rng.normal(0, read_noise_e, img.shape)
    full = bg_e + 4000.0
    dn = np.clip(img / full * 255.0, 0, 255).astype(np.uint8)

    zen_world_down = np.array([0.0, 0.0, -1.0])
    g_cam = np.array([zen_world_down @ r, zen_world_down @ d, zen_world_down @ f])
    in_frame = ok & (m_obs < 6.5)
    meta = dict(lat=lat, lon=lon, utc=t.isot + "Z", az=az, alt=alt, roll=roll, hfov=hfov, width=width,
                height=height, elevation_m=elevation_m, focal_px=fpx, seed=seed, dropout=dropout,
                psf_sigma=psf_sigma, bg_e=bg_e, glow_e=glow_e, mag6_peak_snr=mag6_peak_snr,
                read_noise_e=read_noise_e, extinction_k=extinction_k, refraction=refraction, max_mag=max_mag,
                gravity_cam=g_cam.tolist(), zenith_cam=(-g_cam).tolist(),
                camera_frame="x=image right, y=image down, z=out of lens; gravity_cam points down",
                n_stars_projected=int(ok.sum()), n_stars_rendered=int(keep.sum()), n_dropped=n_drop,
                n_stars_brighter_6p5=int(in_frame.sum()), catalog="Hipparcos hip_main.dat, pm to epoch",
                generator="skyfix/synth/render_sky.py")
    return dn, meta


def save(dn, meta, out):
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(dn).save(out)
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True); ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--utc", required=True); ap.add_argument("--az", type=float, required=True)
    ap.add_argument("--alt", type=float, required=True); ap.add_argument("--roll", type=float, default=0.0)
    ap.add_argument("--hfov", type=float, default=70.0); ap.add_argument("--width", type=int, default=2000)
    ap.add_argument("--height", type=int, default=1500); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dropout", type=float, default=0.03); ap.add_argument("--elevation", type=float, default=0.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    dn, meta = render(a.lat, a.lon, a.utc, a.az, a.alt, a.roll, a.hfov, a.width, a.height, a.elevation, a.seed, a.dropout)
    print(save(dn, meta, a.out), meta["n_stars_rendered"], "stars")


if __name__ == "__main__":
    sys.exit(main())
