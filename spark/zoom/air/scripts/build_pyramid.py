"""NOAA ERI GeoTIFFs (EPSG:4326) -> small web-tile pyramid (512 px WebP tiles, lat/lon-linear) + overview PNG + world file.

Usage: build_pyramid.py <tif_dir> <out_dir> [max_level]
Level k has ground resolution res0 * 2**(L-k) where the finest level L is ~0.2 m/px.
Writes out_dir/meta.json {bounds, levels:[{z, w, h, tx, ty, m_per_px}], gsd_native_m, sources}.
"""
import sys, json, math, glob
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from PIL import Image

TILE = 512


def main(src, out, max_level=4):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    files = sorted(glob.glob(f"{src}/*.tif"))
    ds = []
    for f in files:
        try:
            d = rasterio.open(f); d.read(1, window=((0, 1), (0, 1)))  # fails on truncated downloads
            d.read(1, out_shape=(1, 8, 8))                           # touches the overview chain too
            ds.append(d)
        except Exception as e:
            print("skip", f, e)
    W = min(d.bounds.left for d in ds); E = max(d.bounds.right for d in ds)
    S = min(d.bounds.bottom for d in ds); N = max(d.bounds.top for d in ds)
    lat0 = (S + N) / 2
    mx = 111320 * math.cos(math.radians(lat0)); my = 110540
    gsd = ds[0].res[0] * my
    ext_e, ext_n = (E - W) * mx, (N - S) * my
    levels = []
    for z in range(max_level + 1):
        mpp = 0.2 * 2 ** (max_level - z)
        w, h = max(1, round(ext_e / mpp)), max(1, round(ext_n / mpp))
        tx, ty = math.ceil(w / TILE), math.ceil(h / TILE)
        levels.append({"z": z, "w": w, "h": h, "tx": tx, "ty": ty, "m_per_px": mpp})
        (out / str(z)).mkdir(exist_ok=True)
        dlon, dlat = (E - W) / w, (N - S) / h
        for j in range(ty):
            for i in range(tx):
                x0, y0 = i * TILE, j * TILE
                pw, ph = min(TILE, w - x0), min(TILE, h - y0)
                tw, te_ = W + x0 * dlon, W + (x0 + pw) * dlon
                tn, ts = N - y0 * dlat, N - (y0 + ph) * dlat
                canvas = np.zeros((ph, pw, 4), np.uint8)
                for d in ds:
                    b = d.bounds
                    l, r_ = max(tw, b.left), min(te_, b.right)
                    bt, tp = max(ts, b.bottom), min(tn, b.top)
                    if l >= r_ or bt >= tp:
                        continue
                    px0 = int(round((l - tw) / dlon)); px1 = int(round((r_ - tw) / dlon))
                    py0 = int(round((tn - tp) / dlat)); py1 = int(round((tn - bt) / dlat))
                    if px1 <= px0 or py1 <= py0:
                        continue
                    win = from_bounds(l, bt, r_, tp, d.transform)
                    a = d.read([1, 2, 3, 4], window=win, out_shape=(4, py1 - py0, px1 - px0),
                               resampling=Resampling.average).transpose(1, 2, 0)
                    m = a[..., 3] > 0
                    sub = canvas[py0:py1, px0:px1]
                    sub[m] = a[m]
                if canvas[..., 3].any():
                    Image.fromarray(canvas, "RGBA").save(out / str(z) / f"{i}_{j}.webp", quality=80, method=4)
        print(f"level {z}: {w}x{h} px, {tx}x{ty} tiles, {mpp} m/px", flush=True)
    # overview PNG + world file (level 0)
    L0 = levels[0]
    ov = Image.new("RGBA", (L0["w"], L0["h"]))
    for j in range(L0["ty"]):
        for i in range(L0["tx"]):
            p = out / "0" / f"{i}_{j}.webp"
            if p.exists():
                ov.paste(Image.open(p), (i * TILE, j * TILE))
    ov.save(out / "overview.png")
    dlon, dlat = (E - W) / L0["w"], (N - S) / L0["h"]
    (out / "overview.pgw").write_text(f"{dlon:.12f}\n0\n0\n{-dlat:.12f}\n{W + dlon/2:.12f}\n{N - dlat/2:.12f}\n")
    meta = {"bounds": {"w": W, "e": E, "s": S, "n": N}, "lat0": lat0, "extent_m": [round(ext_e), round(ext_n)],
            "gsd_native_m": round(gsd, 3), "levels": levels, "tile": TILE,
            "sources": [Path(d.name).name for d in ds],
            "attribution": "Imagery: NOAA National Geodetic Survey Emergency Response Imagery."}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: meta[k] for k in ("bounds", "extent_m", "gsd_native_m", "sources")}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
