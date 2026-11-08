"""Build data/landmarks.json: downtown Boston landmarks with lat/lon, top height, ground elevation, citations.

Position: OpenStreetMap footprint centre (Overpass, `out center`/`out geom`; raw responses in data/osm_*_raw.json).
Top height: Wikipedia infobox 'roof' / 'height' (raw wikitext in data/wiki_*.txt), cross-checked with the OSM height tag.
Ground: USGS 3DEP 1 m via EPQS (NAVD88 metres), so top_asl_m = ground_m + height_m.
Usage: ~/forge/.venv/bin/python build_landmarks.py
"""
import json, urllib.request
from pathlib import Path
D = Path(__file__).resolve().parent / "data"
FT = 0.3048
W = "https://en.wikipedia.org/wiki/"
L = [
 dict(id="custom_house", name="Custom House Tower", lat=42.359045, lon=-71.053567, height_m=496*FT, osm="way/29719177", osm_height="151",
      wiki=W+"Custom_House_Tower", wiki_height="roof 496 ft (151 m)", note="top = pinnacle above the clock; bearing to the tower centreline"),
 dict(id="harbor_towers_1", name="Harbor Towers I", lat=42.358119, lon=-71.049806, height_m=400*FT, osm="way/240415950", osm_height="121",
      wiki=W+"Harbor_Towers", wiki_height="taller tower stands at 400 ft", note="north-east tower of the pair"),
 dict(id="harbor_towers_2", name="Harbor Towers II", lat=42.35767, lon=-71.050489, height_m=396*FT, osm="way/240415949", osm_height="120",
      wiki=W+"Harbor_Towers", wiki_height="other tower rises 396 ft", note="south-west tower of the pair"),
 dict(id="one_intl_place", name="One International Place", lat=42.355706, lon=-71.05215, height_m=600*FT, osm="way/241176918", osm_height="183",
      wiki=W+"One_International_Place", wiki_height="roof 600 ft (183 m)", note=""),
 dict(id="millennium_tower", name="Millennium Tower", lat=42.355705, lon=-71.059507, height_m=684*FT, osm="way/95035761", osm_height="209",
      wiki=W+"Millennium_Tower_(Boston)", wiki_height="roof 684 ft", note=""),
 dict(id="state_street_bank", name="State Street Bank Building (225 Franklin St)", lat=42.356134, lon=-71.053938, height_m=477*FT,
      osm="way/139980427", osm_height="145.39", wiki=W+"State_Street_Bank_Building", wiki_height="roof 477 ft", note="OSM names it 225 Franklin Street"),
 dict(id="faneuil_cupola", name="Faneuil Hall cupola", lat=42.36001, lon=-71.05608, height_m=None, osm="way/29551702", osm_height=None,
      wiki=W+"Faneuil_Hall", wiki_height="none given; cupola 'moved to the eastern end' of the roof (1806)",
      note="position = east end of the OSM footprint (lon range -71.05644..-71.05603), ~4 m inside; height UNKNOWN, bearing-only; UNVERIFIED: no published height (pack uses ~29 m, flagged)", verified=False),
 dict(id="zakim_south", name="Zakim Bridge south tower", lat=42.368014, lon=-71.062275, height_m=270*FT, osm="way/485005954", osm_height="98",
      wiki=W+"Leonard_P._Zakim_Bunker_Hill_Memorial_Bridge", wiki_height="height 270 ft (82 m)",
      note="Height 82 m (Wikipedia 270 ft) is used. OSM tags these pylons height=98; the operator judged the OSM tag wrong (2026-11-08). Discrepancy 16 m noted, not used."),
 dict(id="zakim_north", name="Zakim Bridge north tower", lat=42.369575, lon=-71.064057, height_m=270*FT, osm="way/485005963", osm_height="98",
      wiki=W+"Leonard_P._Zakim_Bunker_Hill_Memorial_Bridge", wiki_height="height 270 ft (82 m)",
      note="Height 82 m (Wikipedia 270 ft) is used. OSM tags these pylons height=98; the operator judged the OSM tag wrong (2026-11-08). Discrepancy 16 m noted, not used."),
 dict(id="bunker_hill", name="Bunker Hill Monument", lat=42.376352, lon=-71.060767, height_m=221*FT, osm="way/212124093", osm_height="67",
      wiki=W+"Bunker_Hill_Monument", wiki_height="rises 221 ft", note="stands on Breed's Hill: ground elevation matters here"),
]
def epqs(lat, lon):
    u = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Meters&wkid=4326"
    for k in range(4):
        try:
            r = urllib.request.Request(u, headers={"User-Agent": "skyfix-city/0.1"})
            return float(json.loads(urllib.request.urlopen(r, timeout=40).read())["value"])
        except Exception as e:
            err = e
    raise err
for l in L:
    l["ground_m"] = round(epqs(l["lat"], l["lon"]), 1)
    l["height_m"] = None if l["height_m"] is None else round(l["height_m"], 1)
    l["top_asl_m"] = None if l["height_m"] is None else round(l["ground_m"] + l["height_m"], 1)
    l["osm_url"] = "https://www.openstreetmap.org/" + l["osm"]
out = {"landmarks": L, "sources": {"position": "OpenStreetMap (ODbL), Overpass API, footprint centre",
       "height": "English Wikipedia infobox / text (CC BY-SA), fetched 2026-11-08", "ground": "USGS 3DEP 1 m via EPQS, NAVD88 m"},
       "reference": {"name": "60 State Street (Franco's stated position)", "lat": 42.3590, "lon": -71.0565}}
(D / "landmarks.json").write_text(json.dumps(out, indent=1))
for l in L: print(f"{l['name']:45s} {l['lat']:.6f} {l['lon']:.6f} h={l['height_m']} ground={l['ground_m']} top_asl={l['top_asl_m']}")
