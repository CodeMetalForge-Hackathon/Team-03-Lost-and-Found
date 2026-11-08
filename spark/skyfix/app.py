"""Sky Fix service (FastAPI, port 8130). Phone-first PWA at /, glasses HUD at /?hud=1, judge gallery at /demo.
Everything runs offline. Nothing is transmitted: fixes go to the local hash-chained evidence log + CoT files."""
from __future__ import annotations
import hashlib, io, json, math, os, pathlib, sys, threading, time, zlib
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from PIL import Image, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import solver_stars as STARS  # noqa: E402
import solver_skyline as SKY  # noqa: E402
import ch1  # noqa: E402
from evidence import Evidence  # noqa: E402
from rb.geo import haversine_m, bearing_deg, compass8  # noqa: E402  (rescuebase-forge, reused unchanged)

app = FastAPI(title="Sky Fix", docs_url="/api/docs")
EV = Evidence()
SOLVE_LOCK = threading.Lock()
RP = json.loads((ROOT / "config" / "recovery_points.json").read_text())
MAX_UPLOAD = 30 * 1024 * 1024
THUMBS = ROOT / "cache" / "thumbs"
THUMBS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- demo catalogue (id -> file + truth)
def _catalogue():
    items = {}
    for j in sorted((ROOT / "synth" / "frames").glob("*.json")):
        if j.name == "manifest.json":
            continue
        m = json.loads(j.read_text())
        items[f"synth:{j.stem}"] = dict(id=f"synth:{j.stem}", set="synthetic", mode="night", path=str(j.with_suffix(".png")),
                                        title=f"{m['site']} az{int(m['az'])} alt{int(m['alt'])}", utc=m["utc"].rstrip("Z"),
                                        gravity=m["gravity_cam"], truth=dict(lat=m["lat"], lon=m["lon"], heading=m["az"]),
                                        elevation_m=m["elevation_m"], credit="synthetic (Hipparcos), exact ground truth")
    for w in json.loads((ROOT / "data/sky_photos/index_enriched.json").read_text()):
        try:
            Image.open(ROOT / "data/sky_photos" / w["file"]).verify()
        except Exception:  # e.g. a downloader saved an HTML error page under a .jpg name
            continue
        k = f"wiki:{zlib.crc32(w['file'].encode()):08x}"
        items[k] = dict(id=k, set="wikimedia", mode="night", path=str(ROOT / "data/sky_photos" / w["file"]), title=w["title"][5:60],
                        utc=None, gravity=None, truth=dict(lat=w["lat"], lon=w["lon"]), credit=f"{w.get('artist', '')} · {w['license']}",
                        source=w.get("source"))
    # Pixel phone photos: deterministic sample = first 6 solved + first 6 unsolved of the EXIF-timed set with GPS (by filename)
    try:
        rr = [r for r in json.loads((ROOT / "results/stars_real.json").read_text()) if r["set"] == "astrosmartphone" and r.get("lat")]
        rr.sort(key=lambda r: r["path"])
        pick = [r for r in rr if r["solved"]][:6] + [r for r in rr if not r["solved"]][:6]
        for r in pick:
            k = f"pixel:{zlib.crc32(r['path'].encode()):08x}"
            items[k] = dict(id=k, set="pixel", mode="night", path=r["path"], title=f"{r['subset']} {pathlib.Path(r['path']).stem[:24]}",
                            utc=r.get("utc"), gravity=None, truth=dict(lat=r["lat"], lon=r["lon"]),
                            credit="AstroSmartphoneDataset (Google Pixel night sight)")
    except FileNotFoundError:
        pass
    _, test = ch1.split()
    for it in test[:10]:  # first 10 TEST locations in split order: not cherry-picked
        k = f"ch1:{it['id']}"
        items[k] = dict(id=k, set="ch1", mode="day", path=it["path"], title=f"CH1 {it['id'][:24]}", focal_px=it["focal_px"],
                        prior=dict(lat=it["prior_lat"], lon=it["prior_lon"], offset_km=it["prior_offset_km"]), grid_key=it["loc_key"],
                        truth=dict(lat=it["lat"], lon=it["lon"]), credit="CH1 query set (Baatz et al. ECCV 2012), CVG ETH Zurich / Panoramio users")
    return items


CAT = _catalogue()


# ---------------------------------------------------------------- helpers
def recovery(lat, lon):
    best = min(RP["areas"], key=lambda a: haversine_m(lat, lon, a["points"][0]["lat"], a["points"][0]["lon"]))
    pts = []
    for p in best["points"]:
        d = haversine_m(lat, lon, p["lat"], p["lon"])
        b = bearing_deg(lat, lon, p["lat"], p["lon"])
        pts.append(dict(p, dist_km=round(d / 1000, 1), bearing_deg=round(b), compass=compass8(b)))
    return dict(ao=best["ao"], points=pts, target=pts[0])


def err_km(lat, lon, t):
    return round(math.hypot((lat - t["lat"]) * 111.195, ((lon - t["lon"] + 180) % 360 - 180) * 111.195 * math.cos(math.radians(t["lat"]))), 2)


def tilt_noise(g, sigma_deg, seed):
    rng = np.random.default_rng(seed)
    g = np.asarray(g, float); g /= np.linalg.norm(g)
    a = np.cross(g, [1.0, 0, 0]); a /= np.linalg.norm(a); b = np.cross(g, a)
    tx, ty = np.deg2rad(rng.normal(0, sigma_deg, 2))
    v = g + tx * a + ty * b
    return (v / np.linalg.norm(v)).tolist(), round(math.degrees(math.hypot(tx, ty)), 3)


def device_to_camera_down(ax, ay, az, screen_angle=0):
    """DeviceMotion accelerationIncludingGravity (W3C: points UP at rest; x right, y up, z out of screen)
    -> DOWN direction in the back-camera image frame (x right, y down, z out of lens). Portrait tested only."""
    th = math.radians(screen_angle or 0)  # screen.orientation.angle: 90 = landscape-primary (device top to the left)
    x = ax * math.cos(th) - ay * math.sin(th)
    y = ax * math.sin(th) + ay * math.cos(th)
    up_cam = (x, -y, -az)
    return [-up_cam[0], -up_cam[1], -up_cam[2]]


def thumb(path, w=360):
    key = hashlib.sha1(f"{path}:{w}".encode()).hexdigest()[:16]
    f = THUMBS / f"{key}.jpg"
    if not f.exists():
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        if "synth" in str(path):  # synthetic frames are dark: stretch for the thumbnail only
            a = np.asarray(im, np.float32); a = np.clip((a - 20) * 4, 0, 255).astype(np.uint8); im = Image.fromarray(a)
        im.thumbnail((w, w))
        im.save(f, quality=82)
    return f


def finish(res: dict, demo: dict | None, image_sha: str, extra: dict) -> dict:
    """Recovery bearing + evidence log + CoT for a successful fix."""
    fx = res.get("fix_out")
    if fx:
        res["recovery"] = recovery(fx["lat"], fx["lon"])
        rec = dict(solver=res["solver"], lat=round(fx["lat"], 6), lon=round(fx["lon"], 6), ring_m=round(fx["ring_km"] * 1000, 0),
                   heading_deg=None if fx.get("heading_deg") is None else round(fx["heading_deg"], 1), confidence=fx.get("confidence"),
                   image_sha256=image_sha, demo_id=demo["id"] if demo else None, utc=extra.get("utc"),
                   recovery_target=res["recovery"]["target"]["name"], recovery_bearing_deg=res["recovery"]["target"]["bearing_deg"],
                   recovery_dist_km=res["recovery"]["target"]["dist_km"], truth_err_km=res.get("truth", {}).get("err_km"),
                   inputs={k: v for k, v in extra.items() if k != "utc"})
        rec = EV.append(rec)
        res["evidence"] = dict(uid=rec["uid"], seq=rec["seq"], hash=rec["hash"], prev_hash=rec["prev_hash"], logged_utc=rec["logged_utc"])
        res["cot"] = EV.write_cot(rec)
    return res


@app.on_event("startup")
def _warm():
    """Load tetra3 databases, the DEM mosaic and SAM 2 in the background so the first demo click is fast."""
    def w():
        try:
            STARS._t3("phone"); STARS._t3("default"); SKY._dem()
            import horizon
            horizon._sam()
        except Exception as e:  # noqa: BLE001
            print("warm-up:", repr(e))
    if not os.environ.get("SKYFIX_NO_WARM"):
        threading.Thread(target=w, daemon=True).start()


# ---------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/demo", response_class=HTMLResponse)
def demo_page():
    return FileResponse(ROOT / "web" / "demo.html")


@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse({"name": "Sky Fix", "short_name": "Sky Fix", "start_url": "/", "display": "standalone",
                         "background_color": "#000000", "theme_color": "#000000",
                         "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]})


@app.get("/icon.svg")
def icon():
    return Response('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#000"/>'
                    '<path d="M50 8 L58 42 L92 50 L58 58 L50 92 L42 58 L8 50 L42 42Z" fill="#ffd400"/></svg>', media_type="image/svg+xml")


@app.get("/sw.js")
def sw():
    js = """const C='skyfix-v1';self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['/','/demo','/icon.svg']))));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET'||e.request.url.includes('/api/'))return;
e.respondWith(fetch(e.request).then(r=>{const k=r.clone();caches.open(C).then(c=>c.put(e.request,k));return r}).catch(()=>caches.match(e.request)))});"""
    return Response(js, media_type="application/javascript")


# ---------------------------------------------------------------- API
@app.get("/api/health")
def health():
    return dict(ok=True, demo_items=len(CAT), evidence=EV.verify(), phone_db=STARS.PHONE_DB.exists(),
                skyline_grid_step_km=SKY.GRID_STEP_KM, transmits=False)


@app.get("/api/demo_items")
def demo_items(set: str | None = None):
    out = []
    for it in CAT.values():
        if set and it["set"] != set:
            continue
        out.append({k: it[k] for k in ("id", "set", "mode", "title", "credit") if k in it} | {"has_gravity": it.get("gravity") is not None,
                                                                                              "has_utc": bool(it.get("utc"))})
    return out


@app.get("/api/thumb/{item_id}")
def api_thumb(item_id: str, w: int = Query(360, ge=64, le=1024)):
    it = CAT.get(item_id)
    if not it:
        raise HTTPException(404)
    return FileResponse(thumb(it["path"], w), media_type="image/jpeg")


@app.get("/api/recovery_points")
def recovery_points():
    return RP


@app.get("/api/last")
def last():
    recs = EV.records()
    if not recs:
        return dict(ok=False)
    r = recs[-1]
    return dict(ok=True, uid=r["uid"], lat=r["lat"], lon=r["lon"], ring_km=round(r["ring_m"] / 1000, 1), solver=r["solver"],
                heading_deg=r.get("heading_deg"), confidence=r.get("confidence"), target=r["recovery_target"],
                bearing_deg=r["recovery_bearing_deg"], dist_km=r["recovery_dist_km"], logged_utc=r["logged_utc"], demo=bool(r.get("demo_id")))


@app.get("/api/evidence")
def evidence(n: int = Query(20, ge=1, le=500)):
    recs = EV.records()
    return dict(verify=EV.verify(), records=[{k: v for k, v in r.items() if k != "inputs"} for r in recs[-n:]],
                jsonl=str(EV.jsonl.relative_to(ROOT)) if EV.jsonl.is_relative_to(ROOT) else str(EV.jsonl))


@app.get("/api/hillshade")
def hillshade(lat: float, lon: float, km: float = Query(30, ge=2, le=150), px: int = Query(512, ge=128, le=1024)):
    """Hillshade PNG of the terrain model centred on (lat, lon), km wide. Swiss test region only."""
    name = SKY.dem_for(lat, lon, 0.0)
    d = SKY._dem(name) if name else None
    if d is None or not d.contains(lat, lon, margin_deg=km / 2 / 111 / 0.68):
        raise HTTPException(404, "no terrain model here")
    half = km / 2
    cl = math.cos(math.radians(lat))
    ys = lat + np.linspace(half, -half, px) / 111.195
    xs = lon + np.linspace(-half, half, px) / (111.195 * cl)
    r, c = d.rc(ys[:, None] + 0 * xs[None], 0 * ys[:, None] + xs[None])
    from scipy.ndimage import map_coordinates
    z = map_coordinates(d.a, [r.ravel(), c.ravel()], order=1).reshape(px, px)
    cell = km * 1000 / px
    gy, gx = np.gradient(z, cell)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(45)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    img = np.clip(40 + 160 * hs, 0, 255).astype(np.uint8)
    buf = io.BytesIO(); Image.fromarray(img).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


def _solve_night(data: bytes | str, demo, utc, gravity, tilt, fov, elevation_m=0.0, simulate_tilt=True):
    res = dict(solver="stars", mode="night")
    if demo and demo.get("gravity") is not None:
        # synthetic frame: exact gravity from the sidecar, plus a deterministic simulated phone-tilt error (honest default)
        exact = STARS.solve(demo["path"], utc=demo["utc"], gravity=demo["gravity"], tilt=0.0, elevation_m=demo.get("elevation_m", 0))
        res["exact_gravity"] = exact
        if exact.get("ok") and exact.get("fix"):
            res["exact_err_km"] = err_km(exact["fix"]["lat"], exact["fix"]["lon"], demo["truth"])
        if simulate_tilt:
            g, applied = tilt_noise(demo["gravity"], STARS.TILT_SIGMA["braced"], zlib.crc32(demo["id"].encode()))
            r = STARS.solve(demo["path"], utc=demo["utc"], gravity=g, tilt="braced", elevation_m=demo.get("elevation_m", 0))
            res["simulated_tilt_deg"] = applied
        else:
            r = exact
    else:
        r = STARS.solve(data, utc=utc, gravity=gravity, tilt=tilt, fov_estimate=fov, elevation_m=elevation_m)
    res["result"] = r
    res["message"] = r.get("message")
    if r.get("ok") and r.get("fix"):
        f = r["fix"]
        res["fix_out"] = dict(lat=f["lat"], lon=f["lon"], ring_km=f["ring_km"], ring95_km=f["ring95_km"], heading_deg=f["heading_deg"],
                              confidence=f"tilt σ {f['tilt_sigma_deg']}°")
    return res


def _solve_day(img: Image.Image, demo, focal_px, hfov, prior_lat, prior_lon):
    res = dict(solver="skyline", mode="day")
    if demo:
        r = SKY.solve(img, demo["focal_px"], prior_lat=demo["prior"]["lat"], prior_lon=demo["prior"]["lon"], grid_key=demo["grid_key"])
    else:
        if prior_lat is None or prior_lon is None:
            real = [x for x in EV.records() if not x.get("demo_id")]
            lastrec = real[-1] if real else None
            if lastrec:
                prior_lat, prior_lon = lastrec["lat"], lastrec["lon"]
                res["prior_source"] = f"last fix {lastrec['uid']}"
        r = SKY.solve(img, focal_px, hfov, prior_lat=prior_lat, prior_lon=prior_lon)
    res["result"] = r
    res["message"] = r.get("message")
    if r.get("ok"):
        res["fix_out"] = dict(lat=r["lat"], lon=r["lon"], ring_km=r["ring_conf_km"] if r["confident"] else r["ring_km"],
                              ring95_km=r["ring_km"], ring_note=("distinct match: ring = max(core ring, 5 km); dashed = spread of top-5% cells"
                                                                if r["confident"] else "ambiguous: ring = spread of top-5% cells"),
                              heading_deg=r["heading_deg"], confidence="distinct" if r["confident"] else "AMBIGUOUS")
    return res


@app.post("/api/solve")
def solve(file: UploadFile | None = File(None), demo_id: str | None = Form(None), mode: str = Form("night"),
          utc: str | None = Form(None), client_utc: str | None = Form(None), tz_offset_min: int | None = Form(None),
          gravity: str | None = Form(None), device_accel: str | None = Form(None),
          screen_angle: float = Form(0.0), tilt: str = Form("braced"), fov: float | None = Form(None),
          focal_px: float | None = Form(None), prior_lat: float | None = Form(None), prior_lon: float | None = Form(None),
          simulate_tilt: bool = Form(True)):
    t0 = time.time()
    demo = CAT.get(demo_id) if demo_id else None
    if demo_id and not demo:
        raise HTTPException(404, "unknown demo item")
    if demo:
        data = pathlib.Path(demo["path"]).read_bytes()
        mode = demo["mode"]
    elif file is not None:
        data = file.file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "image too large")
    else:
        raise HTTPException(400, "send a photo or a demo_id")
    sha = hashlib.sha256(data).hexdigest()
    g = None
    notes = []

    def vec3(txt, name):
        try:
            v = [float(x) for x in json.loads(txt)]
        except (ValueError, TypeError):
            raise HTTPException(422, f"{name} must be a JSON list of 3 numbers")
        if len(v) != 3 or not all(math.isfinite(x) for x in v) or math.hypot(*v) < 1e-6:
            raise HTTPException(422, f"{name} must be 3 finite numbers, not all zero")
        return v
    if isinstance(tilt, str) and tilt not in STARS.TILT_SIGMA:
        try:
            tv = float(tilt)
        except ValueError:
            raise HTTPException(422, "tilt must be 'braced', 'handheld' or a number of degrees")
        if not (math.isfinite(tv) and 0 <= tv <= 10):
            raise HTTPException(422, "tilt sigma must be between 0 and 10 degrees")
        tilt = tv
    for name, v, lo, hi in (("fov", fov, 5, 180), ("focal_px", focal_px, 10, 100000), ("prior_lat", prior_lat, -90, 90), ("prior_lon", prior_lon, -180, 180)):
        if v is not None and not (math.isfinite(v) and lo <= v <= hi):
            raise HTTPException(422, f"{name} out of range")
    if gravity:
        g = vec3(gravity, "gravity")  # explicit camera-frame DOWN vector: used as given
    elif device_accel:
        a = vec3(device_accel, "device_accel")
        g = device_to_camera_down(a[0], a[1], a[2], screen_angle)
        notes.append("gravity from DeviceMotion (W3C axes), converted to camera frame")
        if mode == "night":
            zc = g[2] / math.hypot(*g)  # = -sin(camera altitude) under the W3C sign
            if abs(zc) < 0.2:
                raise HTTPException(422, "camera within ±12° of the horizon: aim higher for stars (also needed to tell the sensor's sign convention)")
            if zc > 0:
                # camera would point below the horizon -> the platform reports the opposite sign (iOS Safari). Flip.
                g = [-x for x in g]
                notes.append("accelerometer sign flipped (camera would otherwise point below the horizon; iOS convention)")
    try:
        with SOLVE_LOCK:
            if mode == "night":
                if not demo and not utc:
                    try:
                        utc = STARS.exif_utc(data, tz_offset_min)
                        if utc:
                            notes.append("time from photo EXIF")
                    except Exception:
                        utc = None
                    if not utc and client_utc:
                        utc = client_utc
                        notes.append("time from phone clock at upload (no EXIF time): if the photo is older, longitude is off by 0.25°/min")
                res = _solve_night(data, demo, utc, g, tilt, fov, simulate_tilt=simulate_tilt)
            elif mode == "day":
                img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
                res = _solve_day(img, demo, focal_px, fov, prior_lat, prior_lon)
            else:
                raise HTTPException(400, "mode must be night or day")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(dict(ok=False, error=f"solver error: {e!r}"[:300]), status_code=500)
    if demo:
        res["demo"] = {k: demo[k] for k in ("id", "set", "title", "credit") if k in demo}
        if "prior" in demo:
            res["prior"] = demo["prior"]
        if res.get("fix_out"):
            res["truth"] = dict(demo["truth"], err_km=err_km(res["fix_out"]["lat"], res["fix_out"]["lon"], demo["truth"]))
            if "heading" in demo["truth"] and res["fix_out"].get("heading_deg") is not None:
                res["truth"]["heading_err_deg"] = round((res["fix_out"]["heading_deg"] - demo["truth"]["heading"] + 180) % 360 - 180, 2)
        else:
            res["truth"] = dict(demo["truth"])
    res["notes"] = notes
    res["ok"] = bool(res.get("result", {}).get("ok"))
    used_utc = res.get("result", {}).get("utc") or utc
    res = finish(res, demo, sha, dict(utc=used_utc, gravity=g, tilt=tilt, mode=mode, notes=notes))
    res["server_ms"] = round((time.time() - t0) * 1e3)
    return JSONResponse(json.loads(json.dumps(res, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SKYFIX_HOST", "0.0.0.0"), port=int(os.environ.get("SKYFIX_PORT", "8130")))
