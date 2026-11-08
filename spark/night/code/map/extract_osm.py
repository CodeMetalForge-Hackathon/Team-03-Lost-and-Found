"""Extract OSM features within ~10 km of the LKP from ohio-latest.osm.pbf -> map/osm_features.json.
Kinds: road (highway motorway..residential/service/unclassified), trail (path/footway/track/bridleway/cycleway/steps),
water (natural=water, waterway=*, landuse=reservoir/basin), building (centroid + footprint area).
Coordinates rounded to 1e-5 deg (~1 m)."""
import json, math, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))
import osmium

CFG = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
LAT0, LON0 = CFG["lkp"]["lat"], CFG["lkp"]["lon"]
R_KM = 10.5
DLAT = R_KM / 111.32; DLON = R_KM / (111.32 * math.cos(math.radians(LAT0)))
BB = (LAT0 - DLAT, LAT0 + DLAT, LON0 - DLON, LON0 + DLON)
ROAD = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service",
        "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link", "living_street", "road"}
TRAIL = {"path", "footway", "track", "bridleway", "cycleway", "steps", "pedestrian"}


def inbb(lat, lon):
    return BB[0] <= lat <= BB[1] and BB[2] <= lon <= BB[3]


class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__(); self.out = {"road": [], "trail": [], "water": [], "waterline": [], "building": []}

    def way(self, w):
        t = w.tags
        kind = None
        hw = t.get("highway")
        if hw in ROAD: kind = "road"
        elif hw in TRAIL: kind = "trail"
        elif t.get("natural") == "water" or t.get("landuse") in ("reservoir", "basin"): kind = "water"
        elif t.get("waterway") in ("river", "stream", "canal", "ditch", "drain"): kind = "waterline"
        elif "building" in t: kind = "building"
        if not kind:
            return
        try:
            pts = [(n.lat, n.lon) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if not pts or not any(inbb(a, b) for a, b in pts):
            return
        if kind == "building":
            la = sum(p[0] for p in pts) / len(pts); lo = sum(p[1] for p in pts) / len(pts)
            self.out["building"].append([round(la, 5), round(lo, 5)])
        else:
            self.out[kind].append([[round(a, 5), round(b, 5)] for a, b in pts])


t = time.time()
h = H()
h.apply_file(str(Path.home() / "forge/datasets/osm/ohio-latest.osm.pbf"), locations=True, idx="flex_mem")
h.out["bbox"] = BB; h.out["source"] = "OpenStreetMap contributors (ODbL), ohio-latest.osm.pbf (Geofabrik)"
(Path(__file__).resolve().parent / "osm_features.json").write_text(json.dumps(h.out))
print({k: len(v) for k, v in h.out.items() if isinstance(v, list)}, round(time.time() - t), "s")
