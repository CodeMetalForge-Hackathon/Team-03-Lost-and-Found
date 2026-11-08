"""Pre-mission Boston pack: landmarks + building heights + OSM raster tiles for offline use.

Usage: ~/forge/.venv/bin/python build_pack.py [--no-tiles] [--tiles-only]
Bbox: 42.350–42.380 N, −71.075–−71.040 W.
Outputs (city/pack/):
  landmarks.json   name, lat, lon, top_height_m (+ source), aliases, kind, osm id. Built from Overpass:
                   man_made=tower|lighthouse|mast, buildings with height or building:levels (top_height from height, else
                   levels x 3.5 m, marked 'estimated from levels'), place_of_worship with a tower/steeple, bridge pylons,
                   historic=* landmarks. The hand list (HAND) is merged in where Overpass lacks the item; the curated,
                   cited table in data/landmarks.json (Wikipedia heights) overrides heights for the 10 named landmarks.
  buildings.json   every footprint with a height (or levels) for the expected-skyline render: [{h, ground?, ring:[[lat,lon],...]}]
  NOTE 2026-11-08: tile.openstreetmap.org returned its "Access blocked" placeholder for all 313 requests and the first
                   run cached them as tiles. They were deleted (one kept as data/osm_tile_403_blocked_sample.png). The offline map
                   renders pack/buildings.json footprints as vectors instead. The fetcher now verifies every tile and stops on refusal.
  tiles/{z}/{x}/{y}.png  OSM standard tiles z14–17, fetched one at a time with an identifying User-Agent and a delay,
                   skipped if already cached (tile usage policy: https://operations.osmfoundation.org/policies/tiles/).
                   © OpenStreetMap contributors (ODbL); attribution is shown on the map.
"""
import hashlib, json, math, sys, time, urllib.error, urllib.parse, urllib.request
BLOCKED_MD5 = "8e8d1ff492c2bdae445a83ccdb8e449f"   # OSM 'Access blocked' placeholder (data/osm_tile_403_blocked_sample.png)
from pathlib import Path

C = Path(__file__).resolve().parent; P = C / "pack"; P.mkdir(exist_ok=True)
S, N, Wl, E = 42.350, 42.380, -71.075, -71.040
UA = "SkyFix-city-pack/0.1 (offline pre-mission cache for a hackathon SAR prototype; contact via github Team-3)"
OVERPASS = "https://overpass-api.de/api/interpreter"
LEVEL_M = 3.5
HAND = [  # used only if Overpass lacks the item (matched by name)
    dict(name="Custom House Tower", lat=42.359045, lon=-71.053567, top_height_m=151, src="hand list (Wikipedia 496 ft)"),
    dict(name="Harbor Towers I", lat=42.358119, lon=-71.049806, top_height_m=121, src="hand list (Wikipedia 400 ft)"),
    dict(name="Harbor Towers II", lat=42.35767, lon=-71.050489, top_height_m=121, src="hand list"),
    dict(name="Old North Church steeple", lat=42.36632, lon=-71.05444, top_height_m=58, src="hand list (Wikipedia 191 ft)",
         aliases=["Christ Church", "Old North Church"]),
    dict(name="Bunker Hill Monument", lat=42.376352, lon=-71.060767, top_height_m=67, src="hand list (Wikipedia 221 ft)"),
    dict(name="Zakim Bridge south tower", lat=42.368014, lon=-71.062275, top_height_m=82, src="hand list (Wikipedia 270 ft; OSM 98 judged wrong)"),
    dict(name="Zakim Bridge north tower", lat=42.369575, lon=-71.064057, top_height_m=82, src="hand list (Wikipedia 270 ft; OSM 98 judged wrong)"),
    dict(name="Faneuil Hall cupola", lat=42.36001, lon=-71.05608, top_height_m=29, src="hand list (~29 m, unverified)"),
]


def overpass(q):
    for k in range(3):
        try:
            r = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": UA})
            return json.loads(urllib.request.urlopen(r, timeout=180).read())
        except Exception as e:
            err = e; time.sleep(10)
    raise err


def num(s):
    try:
        return float(str(s).lower().replace("m", "").replace(",", ".").split(";")[0].strip())
    except Exception:
        return None


def build_landmarks():
    bb = f"({S},{Wl},{N},{E})"
    q = f"""[out:json][timeout:170];
(
 nwr["man_made"~"^(tower|lighthouse|mast)$"]{bb};
 nwr["building"]["height"]{bb};
 nwr["building"]["building:levels"]{bb};
 nwr["amenity"="place_of_worship"]["tower:type"]{bb};
 nwr["amenity"="place_of_worship"]["building"="church"]{bb};
 nwr["bridge:support"="pylon"]{bb};
 nwr["building"="tower"]{bb};
 nwr["historic"]["name"]{bb};
);
out tags geom;"""
    d = overpass(q); (C / "data/osm_pack_raw.json").write_text(json.dumps(d))
    lms, blds = [], []
    for e in d["elements"]:
        t = e.get("tags", {}); g = e.get("geometry") or ([{"lat": e["lat"], "lon": e["lon"]}] if "lat" in e else [])
        if not g:
            continue
        lat = sum(p["lat"] for p in g) / len(g); lon = sum(p["lon"] for p in g) / len(g)
        h = num(t.get("height")); src = "OSM height" if h else None
        if h is None and num(t.get("building:levels")):
            h = num(t["building:levels"]) * LEVEL_M; src = f"estimated from OSM building:levels x {LEVEL_M} m"
        if e["type"] == "way" and len(g) >= 3 and h and ("building" in t or "building:part" in t):
            blds.append({"h": round(h, 1), "src": "height" if src == "OSM height" else "levels", "ring": [[round(p["lat"], 7), round(p["lon"], 7)] for p in g]})
        name = t.get("name")
        kind = ("tower" if t.get("man_made") in ("tower", "lighthouse", "mast") or t.get("building") == "tower" else
                "pylon" if t.get("bridge:support") == "pylon" else "worship" if t.get("amenity") == "place_of_worship" else
                "historic" if t.get("historic") else "building")
        if kind == "building" and (not name or not h or h < 60):     # only named tall buildings become landmarks
            continue
        if kind in ("historic",) and not name:
            continue
        if not name and kind != "pylon":
            continue
        al = [t[k] for k in ("alt_name", "official_name", "short_name", "old_name") if k in t]
        if "addr:street" in t and "addr:housenumber" in t:
            al.append(f"{t['addr:housenumber']} {t['addr:street']}")
        lms.append({"name": name or f"pylon {e['id']}", "lat": round(lat, 7), "lon": round(lon, 7),
                    "top_height_m": None if h is None else round(h, 1), "top_height_src": src, "aliases": al, "kind": kind,
                    "osm": f"{e['type']}/{e['id']}", "wikidata": t.get("wikidata")})
    # curated cited table overrides (Wikipedia heights) and hand list fills gaps
    cur = json.loads((C / "data/landmarks.json").read_text())["landmarks"]
    by = {l["name"].lower(): l for l in lms}
    for c in cur:
        m = next((l for l in lms if l["osm"] == c["osm"]), None) or by.get(c["name"].lower())
        rec = {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "top_height_m": c["height_m"],
               "top_height_src": f"Wikipedia: {c['wiki_height']} ({c['wiki']})" if c["height_m"] else "unknown", "aliases": [],
               "kind": "curated", "osm": c["osm"], "id": c["id"], "ground_m": c["ground_m"], "note": c.get("note", "")}
        if m:
            rec["aliases"] = sorted(set(m["aliases"] + ([m["name"]] if m["name"] != c["name"] else []))); lms.remove(m)
        lms.append(rec)
    names = {l["name"].lower() for l in lms}
    for h in HAND:
        if h["name"].lower() not in names:
            lms.append({"name": h["name"], "lat": h["lat"], "lon": h["lon"], "top_height_m": h["top_height_m"], "top_height_src": h["src"],
                        "aliases": h.get("aliases", []), "kind": "hand"})
        elif h["name"] == "Faneuil Hall cupola":       # curated entry has no height; use the hand ~29 m, flagged
            l = next(l for l in lms if l["name"].lower() == h["name"].lower())
            if l["top_height_m"] is None:
                l["top_height_m"] = h["top_height_m"]; l["top_height_src"] = h["src"]
    lms.sort(key=lambda l: (l["kind"] != "curated", -(l["top_height_m"] or 0)))
    (P / "landmarks.json").write_text(json.dumps({"bbox": [S, Wl, N, E], "n": len(lms), "landmarks": lms,
        "attribution": "© OpenStreetMap contributors (ODbL); heights for curated items from English Wikipedia (CC BY-SA)"}, indent=1))
    (P / "buildings.json").write_text(json.dumps({"bbox": [S, Wl, N, E], "n": len(blds), "buildings": blds}))
    print(len(lms), "landmarks;", len(blds), "building footprints with height")


def tiles(z0=14, z1=17):
    def xy(lat, lon, z):
        n = 2 ** z; x = (lon + 180) / 360 * n; r = math.radians(lat)
        return int(x), int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * n)
    todo = []
    for z in range(z0, z1 + 1):
        x0, y0 = xy(N, Wl, z); x1, y1 = xy(S, E, z)
        todo += [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    print(len(todo), "tiles z%d-%d" % (z0, z1)); got = 0
    for z, x, y in todo:
        f = P / "tiles" / str(z) / str(x) / f"{y}.png"
        if f.exists() and f.stat().st_size > 0:
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        r = urllib.request.Request(f"https://tile.openstreetmap.org/{z}/{x}/{y}.png", headers={"User-Agent": UA})
        for k in range(3):
            try:
                resp = urllib.request.urlopen(r, timeout=30); b = resp.read()
                if resp.status != 200 or not resp.headers.get("Content-Type", "").startswith("image/") or b[:8] != b"\x89PNG\r\n\x1a\n" \
                        or hashlib.md5(b).hexdigest() == BLOCKED_MD5:
                    print("tile server refused (blocked placeholder) - stopping per tile usage policy"); return
                f.write_bytes(b); got += 1; break
            except urllib.error.HTTPError as e:
                print("tile server refused", e.code, "- stopping per tile usage policy"); return
            except Exception as e:
                print("tile fail", z, x, y, e); time.sleep(5)
        time.sleep(0.6)                                  # one request at a time, gently
    meta = {"zooms": [z0, z1], "n": len(todo), "fetched_now": got, "bbox": [S, Wl, N, E],
            "url": "tiles/{z}/{x}/{y}.png", "attribution": "© OpenStreetMap contributors"}
    (P / "tiles" / "meta.json").write_text(json.dumps(meta, indent=1)); print(meta)


if __name__ == "__main__":
    if "--tiles-only" not in sys.argv:
        build_landmarks()
    if "--no-tiles" not in sys.argv:
        tiles()
