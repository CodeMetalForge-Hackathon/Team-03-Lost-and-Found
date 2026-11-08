"""Zoom to Earth screens on :8150 (AIR theatre + WATER sonar mosaic). Static-file server + small JSON API.

GET /                 index: links to /air and /water
GET /air              NOAA ortho pyramid viewer + live stitch replay + detections + hazard captions + depth relief
GET /water            sonar mosaic forming along the AUV track + call-outs
GET /api/scenes       pyramid scenes available (meta.json of each air/tiles/<scene>)
GET /api/air/<scene>  overlays for a scene: detections, captions, depth availability
GET /api/stitch       frames of the live stitch replay (air/stitch/frames/*.png) + georef
GET /api/water        water mosaic frames + callouts
Files are served from zoom/air/... and zoom/water/... read-only. No external requests from any page.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import threading

sys.path.insert(0, str(Path.home() / "forge/night/fusion"))
import inbox as INBOX  # noqa: E402  night/fusion/inbox.py: the shared file-drop contract

Z = Path(__file__).resolve().parent
AIR, WATER = Z / "air", Z / "water"


def jload(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


EMIT_F = Z / "emitted.json"
_elock = threading.Lock()


def _emitted():
    return jload(EMIT_F, {"air": [], "water": []})


def water_events():
    m = jload(WATER / "mosaic" / "mosaic.json", {})
    out = []
    for i, c in enumerate(m.get("callouts", [])):
        if c["cls"] != "human body":
            continue
        out.append({"id": f"w{i}", "ping": c["ping"], "sensor": "sonar_fls", "kind": "sonar_human_body", "confidence": c["conf"],
                    "position": {"lat": c["lat"], "lon": c["lon"]},
                    "extra": {"detector": "YOLO11n trained on UATD (water/RESULTS.md)", "frame": "UATD_Test_2/" + c["frame"],
                              "range_m": c["range_m"], "bearing_deg": c["bearing_deg"], "pose": [c["pose_lat"], c["pose_lon"]],
                              "simulated_placement": True, "placement": "UATD frame placed along a real AUV track translated onto Hinckley Lake"}})
    return out


def air_events():
    ev = jload(AIR / "air_events.json", {"events": []})["events"]
    return [{**e, "id": f"a{i}"} for i, e in enumerate(ev)]


def _emit(kind, evs):
    with _elock:
        st = _emitted(); done = set(st[kind]); new = []
        for e in evs:
            if e["id"] in done:
                continue
            p = INBOX.emit(e["sensor"], e["kind"], float(e["confidence"]), e["position"], None, None, e.get("extra"))
            st[kind].append(e["id"]); new.append({"id": e["id"], "file": p.name})
        EMIT_F.write_text(json.dumps(st))
    return {"emitted": new, "total_emitted": len(st[kind])}


def make_app():
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.post("/api/emit/air")
    def emit_air(t: float):
        """Drone replay at time t (s): drop every AIR event with t_rel <= t into night/inbox (once each)."""
        return _emit("air", [e for e in air_events() if e["t_rel"] <= t])

    @app.post("/api/emit/water")
    def emit_water(ping: int):
        """Sonar replay at ping k: drop every human-body call-out with ping < k into night/inbox (once each)."""
        return _emit("water", [e for e in water_events() if e["ping"] < ping])

    @app.post("/api/emit/reset")
    def emit_reset(kind: str = "all"):
        """Forget what was emitted (the inbox/chain itself is archived by night/run_all.sh, never deleted here)."""
        with _elock:
            st = _emitted()
            for k in (["air", "water"] if kind == "all" else [kind]):
                st[k] = []
            EMIT_F.write_text(json.dumps(st))
        return st

    @app.get("/api/events")
    def events():
        return {"air": air_events(), "water": water_events(), "emitted": _emitted()}
    (AIR / "tiles").mkdir(parents=True, exist_ok=True)
    (AIR / "stitch").mkdir(parents=True, exist_ok=True)
    (WATER / "mosaic").mkdir(parents=True, exist_ok=True)
    app.mount("/tiles", StaticFiles(directory=AIR / "tiles"), name="tiles")
    app.mount("/stitch", StaticFiles(directory=AIR / "stitch"), name="stitch")
    app.mount("/wmosaic", StaticFiles(directory=WATER / "mosaic"), name="wmosaic")
    app.mount("/ui", StaticFiles(directory=Z / "ui"), name="ui")
    if (WATER / "uatd/UATD_Test_2/images").exists():
        app.mount("/wraw", StaticFiles(directory=WATER / "uatd/UATD_Test_2/images"), name="wraw")

    @app.get("/")
    def index():
        return HTMLResponse((Z / "ui" / "index.html").read_text())

    @app.get("/air")
    def air():
        return HTMLResponse((Z / "ui" / "air.html").read_text())

    @app.get("/water")
    def water():
        return HTMLResponse((Z / "ui" / "water.html").read_text())

    @app.get("/api/scenes")
    def scenes():
        out = {}
        for d in sorted((AIR / "tiles").iterdir()):
            m = jload(d / "meta.json")
            if m:
                m["have"] = {f"{q.parent.name}/{q.stem}": 1 for q in d.glob("[0-9]*/*.webp")}
                out[d.name] = m
        return out

    @app.get("/api/air/{scene}")
    def air_scene(scene: str):
        d = AIR / "tiles" / scene
        if not (d / "meta.json").exists():
            raise HTTPException(404)
        return {"detections": jload(d / "detections.json", {"dets": [], "note": "detector not run on this scene yet"}),
                "captions": jload(d / "captions.json", {"chips": [], "note": "captions not run on this scene"}),
                "depth": (d / "depth" / "meta.json").exists(),
                "pins": jload(AIR / "victim_pins.json", {"pins": []})}

    @app.get("/api/stitch")
    def stitch():
        return jload(AIR / "stitch" / "stitch.json", {"frames": [], "note": "stitch not run yet"})

    @app.get("/api/water")
    def water_api():
        return jload(WATER / "mosaic" / "mosaic.json", {"frames": [], "note": "mosaic not built yet"})

    @app.get("/api/results")
    def results():
        return {"heridal": jload(AIR / "heridal_eval.json"), "uatd": jload(WATER / "uatd_results.json"),
                "land": jload(Z / "land" / "results.json")}

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(make_app(), host="0.0.0.0", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8150, log_level="warning")
