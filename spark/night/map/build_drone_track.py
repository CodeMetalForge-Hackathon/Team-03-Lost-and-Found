"""Real drone track for the ortho reveal: ODM's shots.geojson (Aukerman, 77 photos, Sony DSC-WX220) ->
map/drone_track.json, sorted by capture time. Read-only on ~/forge/tmp/odm.

Footprint: horizontal FOV from ODM's normalised focal length (fov = 2·atan(0.5/f)); height above ground =
camera altitude (HAE, from ODM) − (DEM elevation (EGM96) + geoid undulation). The geoid undulation near
Cleveland is about −34 m (EGM96); stated as an approximation."""
import json, math
from pathlib import Path
import rasterio

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE.parent / "config.json").read_text())
LAT0, LON0 = CFG["lkp"]["lat"], CFG["lkp"]["lon"]; R = 6371008.8
G = json.loads((Path.home() / "forge/tmp/odm/aukerman/odm_report/shots.geojson").read_text())["features"]
GEOID = -34.0
dem = rasterio.open(str(Path.home() / "forge/skyfix/data/dem/N41W082.tif"))
shots = []
for f in G:
    p = f["properties"]; lon, lat, alt = f["geometry"]["coordinates"]
    ground = float(next(dem.sample([(lon, lat)]))[0]) + GEOID
    agl = alt - ground
    fx = p["focal"]; fovx = 2 * math.atan(0.5 / fx); fovy = 2 * math.atan(0.5 * p["height"] / p["width"] / fx)
    w, h = 2 * agl * math.tan(fovx / 2), 2 * agl * math.tan(fovy / 2)
    e = math.radians(lon - LON0) * R * math.cos(math.radians(LAT0)); n = math.radians(lat - LAT0) * R
    shots.append({"t": p["capture_time"], "file": p["filename"], "lat": lat, "lon": lon, "e": round(e, 1), "n": round(n, 1),
                  "agl_m": round(agl, 1), "footprint_m": [round(w, 1), round(h, 1)]})
shots.sort(key=lambda s: s["t"])
t0 = shots[0]["t"]
for s in shots:
    s["t_rel"] = s["t"] - t0
out = {"source": "ODM odm_data_aukerman shots.geojson (real camera positions + capture times)", "geoid_m": GEOID,
       "duration_s": shots[-1]["t_rel"], "shots": shots}
(HERE / "drone_track.json").write_text(json.dumps(out, indent=0))
agl = sorted(s["agl_m"] for s in shots)
print(len(shots), "shots, duration", out["duration_s"], "s; AGL median", agl[len(agl) // 2], "m; footprint", shots[0]["footprint_m"])
