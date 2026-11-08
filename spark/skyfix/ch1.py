"""CH1 (Baatz et al., 'Large Scale Visual Geo-Localization of Images in Mountainous Terrain') loader + split.
Metadata per image `<name>.png.txt`, one item per line: focal length (px), GT latitude, GT longitude, unused (-1),
width, height, image name. `<name>-mask.png` = GT sky mask (sky black) — used only to score horizon extraction.

Split (seeded, by location so near-duplicate shots never straddle the split): 142 unique locations
(rounded to 1e-3 deg) shuffled with seed 7; first 30 locations = DEV (method choices), rest = TEST (reported).
Each location contributes its first image (sorted by name). Each location also gets a seeded 'last known fix'
prior 5-15 km from the truth in a random direction; the 51x51 km search grid is centred on that prior,
so the truth is never at the grid centre or on a grid node."""
import collections, glob, math, pathlib
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
CH1 = ROOT / "data" / "skyline" / "CH1"


def read_meta(txt):
    L = pathlib.Path(txt).read_text().split()
    return dict(focal_px=float(L[0]), lat=float(L[1]), lon=float(L[2]), width=int(L[4]), height=int(L[5]), name=L[6])


def all_images():
    out = []
    for t in sorted(glob.glob(str(CH1 / "*" / "*.png.txt"))):
        m = read_meta(t)
        img = t[:-4]
        m.update(path=img, mask=img[:-4] + "-mask.png", subset=pathlib.Path(t).parent.name,
                 id=pathlib.Path(img).stem, hfov=2 * math.degrees(math.atan(m["width"] / 2 / m["focal_px"])))
        out.append(m)
    return out


def split():
    locs = collections.OrderedDict()
    for m in all_images():
        locs.setdefault((round(m["lat"], 3), round(m["lon"], 3)), []).append(m)
    keys = list(locs)
    rng = np.random.default_rng(7)
    order = rng.permutation(len(keys))
    dev, test = [], []
    for rank, i in enumerate(order):
        m = dict(locs[keys[i]][0])
        r = np.random.default_rng(1000 + int(i))
        d_km, brg = r.uniform(5, 15), r.uniform(0, 360)
        m["prior_lat"] = m["lat"] + d_km * math.cos(math.radians(brg)) / 111.195
        m["prior_lon"] = m["lon"] + d_km * math.sin(math.radians(brg)) / (111.195 * math.cos(math.radians(m["lat"])))
        m["prior_offset_km"] = d_km
        m["loc_key"] = f"{keys[i][0]:.3f}_{keys[i][1]:.3f}"
        (dev if rank < 30 else test).append(m)
    return dev, test


if __name__ == "__main__":
    d, t = split()
    print(len(all_images()), "images;", len(d), "dev locations;", len(t), "test locations")
    print(d[0])
