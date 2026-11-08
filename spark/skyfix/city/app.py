"""Sky Fix city (daytime) mode server. Phone = camera, Spark = solver, over local Wi-Fi; no internet needed at run time
(landmarks, building heights and map tiles come from city/pack/; ground elevation from a cached EPQS lookup or 5 m fallback).

Run: ~/forge/.venv/bin/python app.py 8133 --https     (phones: camera needs a secure context; reuses skyfix/certs read-only)
     ~/forge/.venv/bin/python app.py 8134              (laptop, plain HTTP)
"""
from __future__ import annotations
import io, json, math, re, sys, time, urllib.request
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageOps, ExifTags
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

C = Path(__file__).resolve().parent; SKY = C.parent
sys.path.insert(0, str(C))
import resect as R  # noqa: E402
import vlm  # noqa: E402

CFG = json.loads((C / "config.json").read_text())
UP = C / "uploads"; UP.mkdir(exist_ok=True); CACHE = C / "cache"; CACHE.mkdir(exist_ok=True)
MAXS = 2400                                    # served image long side; taps are in served pixels


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def landmarks():
    f = C / "pack/landmarks.json"
    if f.exists():
        L = json.loads(f.read_text())["landmarks"]
    else:
        L = [{"name": l["name"], "lat": l["lat"], "lon": l["lon"], "top_height_m": l["height_m"], "id": l["id"], "ground_m": l["ground_m"],
              "top_height_src": l["wiki_height"], "kind": "curated", "aliases": []} for l in json.loads((C / "data/landmarks.json").read_text())["landmarks"]]
    out = {}
    for l in L:
        i = l.get("id") or slug(l["name"])
        while i in out and out[i]["name"] != l["name"]:
            i += "_"
        g = l.get("ground_m", 4.0)
        out[i] = dict(l, id=i, top_asl_m=None if l.get("top_height_m") is None else round(l["top_height_m"] + g, 1), ground_m=g)
    return out


GROUND = json.loads((CACHE / "ground.json").read_text()) if (CACHE / "ground.json").exists() else {}


def ground(lat, lon):
    k = f"{lat:.4f},{lon:.4f}"
    if k not in GROUND:
        u = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Meters&wkid=4326"
        r = urllib.request.Request(u, headers={"User-Agent": "skyfix-city/0.1"})
        GROUND[k] = float(json.loads(urllib.request.urlopen(r, timeout=6).read())["value"])
        (CACHE / "ground.json").write_text(json.dumps(GROUND))
    return GROUND[k]


def photo_path(name):
    p = (UP / name) if (UP / name).exists() else (C / name)
    if p.parent not in (C, UP) or not p.exists() or p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".heic"):
        raise FileNotFoundError(name)
    return p


def exif_meta(p):
    im = Image.open(p); ex = im.getexif(); sub = ex.get_ifd(0x8769) if ex else {}
    T = {**{ExifTags.TAGS.get(k, k): v for k, v in ex.items()}, **{ExifTags.TAGS.get(k, k): v for k, v in sub.items()}}
    g = lambda k: T.get(k)  # noqa: E731
    dt = g("DateTimeOriginal"); off = g("OffsetTimeOriginal") or g("OffsetTime")
    when = None
    if dt:
        when = datetime.strptime(str(dt), "%Y:%m:%d %H:%M:%S").isoformat() + (str(off) if off else CFG["default_utc_offset"])
    f35 = g("FocalLengthIn35mmFilm"); fmm = g("FocalLength")
    return {"make": g("Make"), "model": g("Model"), "lens": g("LensModel"), "datetime_original": str(dt) if dt else None,
            "offset": str(off) if off else None, "when_iso": when, "time_zone_assumed": None if off else CFG["default_utc_offset"],
            "f35": int(f35) if f35 else None, "focal_mm": float(fmm) if fmm else None, "orientation": g("Orientation"),
            "gps_in_exif": bool(ex.get_ifd(0x8825)) if ex else False}


def served(p):
    out = CACHE / (p.stem + f"_{int(p.stat().st_mtime)}.jpg")
    if not out.exists():
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB"); full = im.size
        im.thumbnail((MAXS, MAXS)); im.save(out, quality=90)
        (out.with_suffix(".json")).write_text(json.dumps({"full": full, "served": im.size}))
    return out, json.loads(out.with_suffix(".json").read_text())


def lens(meta, W, H, override_hfov=None):
    if override_hfov:
        return R.focal_px(W, H, hfov_fallback=float(override_hfov))
    sw = CFG["sensor_width_mm"].get(meta.get("model") or "", None)
    return R.focal_px(W, H, f35=meta.get("f35"), f_mm=meta.get("focal_mm"), sensor_w_mm=sw, hfov_fallback=CFG["hfov_fallback_deg"])


def recovery(sol, rp):
    loc = R.Local(sol["lat"], sol["lon"]); q = loc.en(rp["lat"], rp["lon"])
    b = math.degrees(math.atan2(q[0], q[1])) % 360; rel = (b - sol["heading_deg"] + 540) % 360 - 180
    return {"name": rp["name"], "lat": rp["lat"], "lon": rp["lon"], "bearing_deg": round(b, 1), "distance_m": round(float((q @ q) ** 0.5), 1),
            "turn": f"{abs(rel):.0f}° {'right' if rel > 0 else 'left'} of the camera's view direction"}


def make_app():
    app = FastAPI(title="Sky Fix city mode")
    vlm.start()
    if (C / "pack/tiles").exists():
        app.mount("/tiles", StaticFiles(directory=str(C / "pack/tiles")), name="tiles")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (C / "web/index.html").read_text()

    @app.get("/health")
    def health():
        return {"ok": True, "vlm": vlm.S["status"], "pack": (C / "pack/landmarks.json").exists()}

    @app.get("/api/config")
    def config():
        return {**CFG, "vlm": {k: vlm.S[k] for k in ("status", "load_s", "error")},
                "tiles": json.loads((C / "pack/tiles/meta.json").read_text()) if (C / "pack/tiles/meta.json").exists() else None}

    @app.get("/api/photos")
    def photos():
        ps = sorted([p.name for p in C.glob("*.jp*g")]) + sorted([p.name for p in UP.glob("*.jp*g")], reverse=True)
        return ps

    @app.post("/api/upload")
    async def upload(request: Request):
        b = await request.body()
        if len(b) < 1000 or len(b) > 40e6:
            raise HTTPException(422, "expected a JPEG body")
        name = time.strftime("phone_%Y%m%d_%H%M%S.jpg"); (UP / name).write_bytes(b)
        return {"name": name}

    @app.get("/api/photo/{name}")
    def photo(name: str, hfov: float | None = None):
        try:
            p = photo_path(name)
        except FileNotFoundError:
            raise HTTPException(404, "no such photo")
        meta = exif_meta(p); out, sz = served(p); W, H = sz["served"]
        f, how, hf = lens(meta, W, H, hfov)
        return {"name": name, "W": W, "H": H, "full": sz["full"], "exif": meta, "f_px": f, "lens_how": how, "hfov_long_deg": round(hf, 2)}

    @app.get("/img/{name}")
    def img(name: str):
        try:
            return FileResponse(served(photo_path(name))[0], media_type="image/jpeg")
        except FileNotFoundError:
            raise HTTPException(404)

    @app.get("/api/landmarks")
    def lms():
        return list(landmarks().values())

    @app.post("/api/propose")
    def propose(d: dict):
        p = photo_path(d["photo"]); out, _ = served(p)
        L = landmarks(); names = [l["name"] for l in L.values() if l["kind"] in ("curated", "hand")]
        r = vlm.propose(Image.open(out).convert("RGB"), names)
        by = {l["name"]: l["id"] for l in L.values()}
        for q in r.get("proposals", []):
            q["id"] = by.get(q["name"])
        return r

    @app.post("/api/solve")
    def solve(d: dict):
        p = photo_path(d["photo"]); meta = exif_meta(p); _, sz = served(p); W, H = sz["served"]
        f, how, hf = lens(meta, W, H, d.get("hfov"))
        L = landmarks()
        try:
            out = R.solve(d["taps"], L, W, H, f, horizon=d.get("horizon") or None, when_iso=meta["when_iso"], ground_fn=ground,
                          ref=CFG.get("reference"), ft_per_floor=float(d.get("ft_per_floor") or CFG["ft_per_floor"]))
        except (ValueError, KeyError) as e:
            raise HTTPException(422, str(e))
        cam = out.pop("_cam")
        out["lens"] = {"f_px": round(f, 1), "how": how, "hfov_long_deg": round(hf, 2)}
        try:                                       # expected skyline from OSM buildings, projected with the solved camera
            import skyline as SK
            hp = (out.get("height") or {}).get("primary")
            h_asl = hp["h_cam_asl_m"] if hp else ground(out["lat"], out["lon"]) + CFG["reference"]["h_above_street_m"]
            sk = SK.render(out["lat"], out["lon"], h_asl); pts = []
            for i, e in enumerate(sk["elev_deg"]):
                az = (i + 0.5) * sk["bin_deg"]; off = math.radians((az - out["heading_deg"] + 540) % 360 - 180)
                if e > -89 and abs(off) < math.radians(80):
                    q = cam.project(off, math.radians(e))
                    if q and -W < q[0] < 2 * W:
                        pts.append([round(q[0], 1), round(q[1], 1)])
            out["skyline_px"] = {"points": pts, "h_asl": round(h_asl, 1), "note": sk["note"] + ("" if hp else "; height = stated 58 m (no horizon taps)")}
        except Exception as e:
            out["skyline_px"] = {"error": f"{type(e).__name__}: {e}"}
        out["recovery"] = recovery(out, CFG["recovery_point"]); out["photo"] = d["photo"]; out["exif_time"] = meta["when_iso"]
        return out

    @app.post("/api/log")
    def log(d: dict):
        sys.path.insert(0, str(SKY))
        from evidence import Evidence     # Sky Fix evidence chain + CoT writer, imported unchanged
        ev = Evidence()
        s = d["solution"]
        rec = ev.append(dict(solver="city_resection", lat=s["lat"], lon=s["lon"], ring_m=float(s["ring_m"]), heading_deg=s["heading_deg"],
                             confidence=("ill-conditioned" if s.get("warnings") else "ok"), photo=s.get("photo"),
                             landmarks=[x["id"] for x in s.get("landmarks", [])],
                             height_m=(s.get("height") or {}).get("primary", {}).get("h_above_ground_m"),
                             floor_est=(s.get("height") or {}).get("primary", {}).get("floor_est"),
                             operator=str(d.get("operator", ""))[:64]))
        cot = ev.write_cot(rec)
        return {"seq": rec["seq"], "uid": rec["uid"], "hash": rec["hash"], "cot": cot, "verify": ev.verify()}

    @app.get("/api/eval")
    def ev():
        f = C / "results/ground_truth.json"
        return json.loads(f.read_text()) if f.exists() else {"none": True}

    @app.get("/api/buildings")
    def buildings():
        return FileResponse(C / "pack/buildings.json", media_type="application/json")

    @app.get("/course", response_class=HTMLResponse)
    def course_page():
        return (C / "web/course.html").read_text()

    @app.get("/api/course")
    def course():
        return json.loads((C / "results/course.json").read_text())

    @app.get("/shots/{name}")
    def shot(name: str):
        f = C / "shots_web" / name
        if f.parent != C / "shots_web" or not f.exists():
            raise HTTPException(404)
        return FileResponse(f, media_type="image/jpeg")

    @app.post("/api/course/log")
    def course_log(d: dict):
        """One hash-chained Sky Fix evidence entry (+ CoT) per fix, then one 'course' summary entry."""
        sys.path.insert(0, str(SKY))
        from evidence import Evidence
        import numpy as np, course as K
        ev = Evidence(); R_ = json.loads((C / "results/course.json").read_text()); op = str(d.get("operator", ""))[:64]; out = []
        for x in R_["shots"]:
            seg = next(s for s in K.SEGS if s["i"] == x["gate"]["segment"])
            rec = ev.append(dict(solver="city_course", lat=x["post_gate"]["lat"], lon=x["post_gate"]["lon"], ring_m=round(seg["L"] / 2, 1),
                                 heading_deg=x["post_gate"]["heading_deg"], confidence="gated" if x["gate"]["heading_rule_ok"] else "gate-heading-rule-failed",
                                 shot=x["shot"], photo_time=x["time"], face=x["gate"]["face"], pre_gate=x["pre_gate"], h_shot=x.get("shot_h"),
                                 ring_note="half the snapped face segment (position along the face is not constrained)", operator=op))
            out.append({"uid": rec["uid"], "hash": rec["hash"], "cot": ev.write_cot(rec)["xsd_valid"]})
        lat = float(np.mean([x["post_gate"]["lat"] for x in R_["shots"]])); lon = float(np.mean([x["post_gate"]["lon"] for x in R_["shots"]]))
        rec = ev.append(dict(solver="city_course_summary", kind="course", lat=lat, lon=lon, ring_m=30.0, heading_deg=None, confidence="summary",
                             fixes=[o["uid"] for o in out], joint_h_m=R_["joint_h_m"], floor_est=R_["floor_est"], direction=R_["direction"],
                             faces=R_["faces"], legs=R_["legs"], total_s=R_["total_s"], operator=op))
        return {"fixes": out, "summary": {"uid": rec["uid"], "hash": rec["hash"]}, "verify": ev.verify()}

    @app.get("/api/skyline")
    def skyline(lat: float, lon: float, h: float, heading: float | None = None, hfov: float | None = None):
        import skyline as SK
        return SK.render(lat, lon, h)

    return app


app = make_app()

if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8133
    kw = dict(ssl_keyfile=str(SKY / "certs/key.pem"), ssl_certfile=str(SKY / "certs/cert.pem")) if "--https" in sys.argv else {}
    uvicorn.run(app, host="0.0.0.0", port=port, **kw)
