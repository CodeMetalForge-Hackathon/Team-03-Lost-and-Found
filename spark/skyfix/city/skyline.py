"""Expected 360° skyline from OSM building footprints with heights (pack/buildings.json): for a candidate camera position
and eye height (m ASL), the maximum elevation angle of any building per azimuth bin. Building base elevation is not in the
pack per footprint, so a flat 4 m ASL ground is assumed for buildings (downtown is 1–9 m by USGS 3DEP); buildings without an
OSM height use levels x 3.5 m. Earth curvature with refraction k=0.13 is applied. Footprints within 20 m of the camera are
skipped (the camera's own building). This is a visual sanity check, not part of the solver."""
import json, math
from pathlib import Path
import numpy as np
from resect import Local, R_EARTH, K_REFR

C = Path(__file__).resolve().parent
_B = None
BIN = 0.25


def _load():
    global _B
    if _B is None:
        _B = json.loads((C / "pack/buildings.json").read_text())["buildings"]
    return _B


def render(lat, lon, h_asl, ground_b=4.0, skip_m=20.0):
    loc = Local(lat, lon); nb = int(360 / BIN); el = np.full(nb, -90.0)
    for b in _load():
        ring = np.array([loc.en(a, o) for a, o in b["ring"]])
        d = np.hypot(ring[:, 0], ring[:, 1])
        if d.min() < skip_m or d.min() > 6000:
            continue
        top = ground_b + b["h"]
        # sample edges densely so wide facades fill their azimuth span
        pts = []
        for i in range(len(ring) - 1):
            a, c = ring[i], ring[i + 1]; L = np.linalg.norm(c - a); k = max(2, int(L / 3))
            pts.append(a + (c - a) * np.linspace(0, 1, k)[:, None])
        P = np.vstack(pts); dd = np.hypot(P[:, 0], P[:, 1])
        e = np.degrees(np.arctan2(top - h_asl - dd * dd / (2 * R_EARTH) * (1 - K_REFR), dd))
        az = (np.degrees(np.arctan2(P[:, 0], P[:, 1])) % 360 / BIN).astype(int) % nb
        np.maximum.at(el, az, e)
    return {"bin_deg": BIN, "elev_deg": [round(float(x), 2) for x in el], "lat": lat, "lon": lon, "h_asl": h_asl,
            "note": "OSM footprints with height; flat 4 m ground for buildings; visual check only"}
