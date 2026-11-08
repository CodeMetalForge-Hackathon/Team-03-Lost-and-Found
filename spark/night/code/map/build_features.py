"""Precompute the static feature grid for the persona map -> map/features.npz (+ features_meta.json).

Grid: local metres east/north of the LKP, 50 m cells, 20 x 20 km (+-10 km), cell centres.
Features per cell: distance (m) to nearest road, trail, water body, stream; building count;
elevation and hillshade from the SRTM-style DEM N41W082.tif (read-only, sampled at cell centres).
"""
import json, math
from pathlib import Path
import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE.parent / "config.json").read_text())
LAT0, LON0 = CFG["lkp"]["lat"], CFG["lkp"]["lon"]
CELL = 50.0
HALF = 10000.0
R = 6371008.8
N = int(2 * HALF / CELL)
SUB = 5            # rasterise lines at CELL/SUB resolution for distance transforms


def ll2en(lat, lon):
    lat = np.asarray(lat); lon = np.asarray(lon)
    return (np.radians(lon - LON0) * R * math.cos(math.radians(LAT0)), np.radians(lat - LAT0) * R)


def en2ll(e, n):
    return LAT0 + np.degrees(n / R), LON0 + np.degrees(e / (R * math.cos(math.radians(LAT0))))


def raster_lines(lines, fine):
    m = np.zeros((N * SUB, N * SUB), bool); res = CELL / SUB
    for ln in lines:
        a = np.array(ln)
        e, n = ll2en(a[:, 0], a[:, 1])
        for i in range(len(e) - 1):
            L = math.hypot(e[i + 1] - e[i], n[i + 1] - n[i]); k = max(2, int(L / (res / 2)))
            ee = np.linspace(e[i], e[i + 1], k); nn = np.linspace(n[i], n[i + 1], k)
            c = ((ee + HALF) / res).astype(int); r = ((HALF - nn) / res).astype(int)
            ok = (c >= 0) & (c < N * SUB) & (r >= 0) & (r < N * SUB)
            m[r[ok], c[ok]] = True
    return m


def raster_polys(polys):
    from matplotlib.path import Path as MPath
    m = np.zeros((N * SUB, N * SUB), bool); res = CELL / SUB
    for pg in polys:
        a = np.array(pg)
        if len(a) < 3:
            continue
        e, n = ll2en(a[:, 0], a[:, 1])
        c = (e + HALF) / res; r = (HALF - n) / res
        c0, c1 = max(0, int(c.min())), min(N * SUB - 1, int(c.max()) + 1)
        r0, r1 = max(0, int(r.min())), min(N * SUB - 1, int(r.max()) + 1)
        if c1 <= c0 or r1 <= r0:
            continue
        yy, xx = np.mgrid[r0:r1 + 1, c0:c1 + 1]
        inside = MPath(np.c_[c, r]).contains_points(np.c_[xx.ravel() + .5, yy.ravel() + .5]).reshape(xx.shape)
        m[r0:r1 + 1, c0:c1 + 1] |= inside
    return m


def dist_cells(mask_fine):
    """Distance (m) from each coarse cell centre to the nearest True fine pixel."""
    if not mask_fine.any():
        return np.full((N, N), 1e6, np.float32)
    d = ndimage.distance_transform_edt(~mask_fine) * (CELL / SUB)
    c = SUB // 2
    return d[c::SUB, c::SUB][:N, :N].astype(np.float32)


def main():
    osm = json.loads((HERE / "osm_features.json").read_text())
    road = dist_cells(raster_lines(osm["road"], True))
    trail = dist_cells(raster_lines(osm["trail"], True))
    wpoly = raster_polys(osm["water"]) | raster_lines(osm["water"], True)
    water = dist_cells(wpoly)
    stream = dist_cells(raster_lines(osm["waterline"], True))
    b = np.array(osm["building"]) if osm["building"] else np.zeros((0, 2))
    bc = np.zeros((N, N), np.int32)
    if len(b):
        e, n = ll2en(b[:, 0], b[:, 1])
        c = ((e + HALF) / CELL).astype(int); r = ((HALF - n) / CELL).astype(int)
        ok = (c >= 0) & (c < N) & (r >= 0) & (r < N)
        np.add.at(bc, (r[ok], c[ok]), 1)
    # DEM
    import rasterio
    ce = -HALF + (np.arange(N) + .5) * CELL; cn = HALF - (np.arange(N) + .5) * CELL
    E, Nn = np.meshgrid(ce, cn)
    lat, lon = en2ll(E, Nn)
    with rasterio.open(str(Path.home() / "forge/skyfix/data/dem/N41W082.tif")) as ds:
        vals = np.array([v[0] for v in ds.sample(zip(lon.ravel(), lat.ravel()))], np.float32).reshape(N, N)
    vals[vals < -1000] = np.nan
    elev = np.where(np.isnan(vals), np.nanmedian(vals), vals)
    gy, gx = np.gradient(elev, CELL)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    az, alt = math.radians(315), math.radians(45)
    asp = np.arctan2(-gx, gy)
    hs = np.sin(alt) * np.cos(np.arctan(np.hypot(gx, gy))) + np.cos(alt) * np.sin(np.arctan(np.hypot(gx, gy))) * np.cos(az - asp)
    rr = np.hypot(E, Nn).astype(np.float32)
    np.savez_compressed(HERE / "features.npz", road=road, trail=trail, water=water, stream=stream, bcount=bc,
                        elev=elev.astype(np.float32), slope=slope.astype(np.float32), hill=hs.astype(np.float32), r=rr)
    meta = {"cell_m": CELL, "half_m": HALF, "n": N, "lkp": CFG["lkp"],
            "dem": "N41W082.tif (1 arc-second, read-only from skyfix/data/dem)",
            "osm": osm["source"], "counts": {k: len(v) for k, v in osm.items() if isinstance(v, list)},
            "cells_with_buildings": int((bc > 0).sum()), "elev_range_m": [float(np.nanmin(elev)), float(np.nanmax(elev))]}
    (HERE / "features_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
