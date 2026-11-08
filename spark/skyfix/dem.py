"""GLO-30 DEM mosaic + 360-degree terrain horizon profiles.

Mosaic: all 1x1 deg GLO-30 tiles in data/dem that belong to one contiguous block are stitched and
downsampled 2x (2 arc-seconds, ~62 m N-S) into cache/dem_<name>.npy (+ .json bounds). Memory-mapped.
Horizon profile at (lat, lon): for each azimuth (1 deg steps) the maximum elevation angle of terrain over
range 90 m..60 km, with Earth curvature and standard refraction (k = 0.13). Observer = DEM + 1.7 m.
"""
from __future__ import annotations
import json, math, pathlib
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
DEM_DIR = ROOT / "data" / "dem"
CACHE = ROOT / "cache"
R_EARTH = 6371.0  # km
K_REFR = 0.13
DISTS_KM = np.concatenate([np.arange(0.09, 3.0, 0.06), np.geomspace(3.0, 60.0, 150)])
AZ = np.arange(360.0)


REGIONS = {  # name: (lat tile range, lon tile range, tile dir)
    "swiss": ((45, 47), (5, 10), DEM_DIR),
    "boston": ((41, 42), (-73, -71), ROOT / "data" / "dem_boston"),  # Blue Hills area (stretch); no test photos
}


def build_mosaic(name: str, lat_range: tuple[int, int], lon_range: tuple[int, int], down: int = 2, dem_dir=None):
    """lat_range/lon_range: inclusive integer tile corners, e.g. (45, 47), (5, 10)."""
    import rasterio
    CACHE.mkdir(exist_ok=True)
    out = CACHE / f"dem_{name}.npy"
    if out.exists():
        return
    nlat, nlon = lat_range[1] - lat_range[0] + 1, lon_range[1] - lon_range[0] + 1
    T = 3600 // down
    mos = np.zeros((nlat * T, nlon * T), np.float32)
    for i, la in enumerate(range(lat_range[1], lat_range[0] - 1, -1)):
        for j, lo in enumerate(range(lon_range[0], lon_range[1] + 1)):
            ns, ew = ("N" if la >= 0 else "S"), ("E" if lo >= 0 else "W")
            f = (dem_dir or DEM_DIR) / f"{ns}{abs(la):02d}{ew}{abs(lo):03d}.tif"
            if not f.exists():
                continue  # sea / missing tile stays 0 m
            a = rasterio.open(f).read(1).astype(np.float32)
            a = np.nan_to_num(a, nan=0.0)
            a = a[: T * down, : T * down].reshape(T, down, T, down).mean((1, 3))
            mos[i * T:(i + 1) * T, j * T:(j + 1) * T] = a
    np.save(out, mos)
    res = down / 3600.0
    # GLO-30 pixel centres sit on whole arc-seconds; tile N46 top edge = 47 + half a 1" pixel
    meta = dict(top=lat_range[1] + 1 + 0.5 / 3600, left=lon_range[0] - 0.5 / 3600, res=res, shape=list(mos.shape), down=down)
    (CACHE / f"dem_{name}.json").write_text(json.dumps(meta))


class DEM:
    def __init__(self, name: str = "swiss"):
        self.a = np.load(CACHE / f"dem_{name}.npy", mmap_mode="r")
        m = json.loads((CACHE / f"dem_{name}.json").read_text())
        self.top, self.left, self.res = m["top"], m["left"], m["res"]
        self.name = name

    def rc(self, lat, lon):
        return (self.top - np.asarray(lat)) / self.res - 0.5, (np.asarray(lon) - self.left) / self.res - 0.5

    def contains(self, lat, lon, margin_deg=0.0):
        r, c = self.rc(lat, lon)
        mr, mc = margin_deg / self.res, margin_deg / self.res
        return (r > mr) and (c > mc) and (r < self.a.shape[0] - mr) and (c < self.a.shape[1] - mc)

    def height(self, lat, lon):
        from scipy.ndimage import map_coordinates
        r, c = self.rc(lat, lon)
        return map_coordinates(self.a, [np.atleast_1d(r), np.atleast_1d(c)], order=1, mode="nearest")

    def profile(self, lat, lon, obs_h_m=1.7, return_dist=False):
        from scipy.ndimage import map_coordinates
        cl = math.cos(math.radians(lat))
        az = np.deg2rad(AZ)[:, None]
        d = DISTS_KM[None, :]
        la = lat + d * np.cos(az) / 111.195
        lo = lon + d * np.sin(az) / (111.195 * cl)
        r, c = self.rc(la, lo)
        h = map_coordinates(self.a, [r.ravel(), c.ravel()], order=1, mode="nearest").reshape(la.shape)
        h0 = float(self.height(lat, lon)[0]) + obs_h_m
        drop = (d * 1000.0) ** 2 / (2 * R_EARTH * 1000.0) * (1 - K_REFR)
        ang = np.degrees(np.arctan2(h - h0 - drop, d * 1000.0))
        i = ang.argmax(1)
        prof = ang[np.arange(360), i]
        return (prof, DISTS_KM[i], h0) if return_dist else prof


def grid_profiles(dem: DEM, lat_c: float, lon_c: float, half_km: float = 25.0, step_km: float = 1.0, obs_h_m=1.7):
    """Profiles on a step_km grid within +/-half_km of (lat_c, lon_c). Returns lats (N,), lons (N,), prof (N,360)."""
    n = int(round(half_km / step_km))
    off = np.arange(-n, n + 1) * step_km
    cl = math.cos(math.radians(lat_c))
    lats, lons = [], []
    for dn in off:
        for de in off:
            lats.append(lat_c + dn / 111.195)
            lons.append(lon_c + de / (111.195 * cl))
    lats, lons = np.array(lats), np.array(lons)
    prof = np.stack([dem.profile(a, b, obs_h_m) for a, b in zip(lats, lons)]).astype(np.float32)
    return lats, lons, prof


def cached_grid(dem: DEM, key: str, lat_c, lon_c, half_km=25.0, step_km=1.0):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"grid_{dem.name}_{key}.npz"
    if f.exists():
        z = np.load(f)
        return z["lats"], z["lons"], z["prof"]
    lats, lons, prof = grid_profiles(dem, lat_c, lon_c, half_km, step_km)
    np.savez_compressed(f, lats=lats, lons=lons, prof=prof, centre=np.array([lat_c, lon_c]), half_km=half_km, step_km=step_km)
    return lats, lons, prof


if __name__ == "__main__":
    import time
    build_mosaic("swiss", (45, 47), (5, 10))
    d = DEM("swiss")
    t = time.time(); p, dist, h0 = d.profile(46.5561, 7.90143, return_dist=True)
    print("h0", h0, "profile ms", (time.time() - t) * 1e3, "max", p.max(), "min", p.min())
