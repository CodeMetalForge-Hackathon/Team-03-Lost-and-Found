"""Persona Search Map + Clue Engine on :8143.

GET  /                      the one-screen map (index.html)
GET  /api/meta              personas, clue table (with provenance), grid geometry, OSM vectors URL
GET  /api/osm               simplified OSM vectors (roads/trails/water/buildings) in local metres
GET  /api/state?persona=    prior, posterior, uncertainty (base64 float32), class masses, top cells,
                            dog coverage, clues, probability captured
POST /api/clue              {type, lat, lon | e, n, note, hours_ago, ce_m, pod, radius_m, operator, photo_b64?}
POST /api/clue/{i}/toggle   switch a clue off/on (the posterior is recomputed; history kept)
POST /api/propose           {photo_b64} -> Qwen3-VL on :8002 proposes a clue type (human must confirm)
GET  /api/contacts          proxied from fusion :8140/contacts
Every clue / persona change is appended to the fusion evidence chain (POST :8140/event) when fusion is up.
"""
from __future__ import annotations
import base64, json, math, sys, threading, time
from pathlib import Path
import numpy as np
import urllib.request

HERE = Path(__file__).resolve().parent
NIGHT = HERE.parent
sys.path.insert(0, str(HERE))
import model as M  # noqa: E402

CFG = json.loads((NIGHT / "config.json").read_text())
FUSION = "http://127.0.0.1:8140"
VLM = "http://127.0.0.1:8002/v1/chat/completions"
CLUES_F = HERE / "clues.json"
STATE_F = HERE / "state.json"
R = 6371008.8
LAT0, LON0 = CFG["lkp"]["lat"], CFG["lkp"]["lon"]
lock = threading.Lock()
clues: list[dict] = json.loads(CLUES_F.read_text()) if CLUES_F.exists() else []


def ll2en(lat, lon):
    return (math.radians(lon - LON0) * R * math.cos(math.radians(LAT0)), math.radians(lat - LAT0) * R)


def en2ll(e, n):
    return LAT0 + math.degrees(n / R), LON0 + math.degrees(e / (R * math.cos(math.radians(LAT0))))


def floor_to_en(x, y):
    a = CFG["floor_anchor"]; e0, n0 = ll2en(a["lat"], a["lon"]); k = float(a.get("scale", 1.0))
    r = math.radians(a.get("rotation_deg", 0.0)); de, dn = x * k, -y * k
    return e0 + de * math.cos(r) + dn * math.sin(r), n0 - de * math.sin(r) + dn * math.cos(r)


def chain(typ, payload):
    try:
        req = urllib.request.Request(FUSION + "/event", data=json.dumps({"type": typ, "payload": payload}).encode(),
                                     headers={"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=1.5).read()
        return True
    except Exception:
        return False


def dog_coverage():
    """Latest dog run (real runs preferred over SYNTHETIC), final POD per floor cell, projected to the map."""
    runs = sorted(NIGHT.glob("data/dog/*/layers.json"),
                  key=lambda p: (json.loads(p.read_text()).get("synthetic", False), -p.stat().st_mtime))
    if not runs:
        return None, []
    L = json.loads(runs[0].read_text()); C = L["coverage"]; pod = np.array(C["snapshots"][-1]["pod"])
    k = float(CFG["floor_anchor"].get("scale", 1.0)); cells = []
    for j in range(C["ny"]):
        for i in range(C["nx"]):
            if pod[j, i] <= 0.01:
                continue
            x = C["x0"] + (i + .5) * C["cell_m"]; y = C["y0"] + (j + .5) * C["cell_m"]
            e, n = floor_to_en(x, y)
            cells.append({"e": e, "n": n, "pod": float(pod[j, i]), "area_m2": (C["cell_m"] * k) ** 2})
    # outline of the floor for drawing
    x0, y0, x1, y1 = L["floor_bounds"]
    outline = [floor_to_en(x, y) for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
    return {"run": runs[0].parent.name, "synthetic": L.get("synthetic", False), "outline_en": outline,
            "cell_map_m": C["cell_m"] * k, "scale": k}, cells


def b64(a):
    return base64.b64encode(np.ascontiguousarray(a, dtype=np.float32).tobytes()).decode()


def compute(persona):
    dog, cells = dog_coverage()
    pod_map = M.coverage_pod(cells) if cells else None
    with lock:
        cl_list = list(clues)
    pr, post, cv, cl, mass, captured = M.posterior(persona, cl_list, pod_map)
    STATE_F.write_text(json.dumps({"persona": persona, "probability_captured": round(captured, 5),
                                   "dog_run": dog and dog["run"], "n_clues": len(cl_list), "t": time.time()}))
    return pr, post, cv, cl, mass, captured, dog, cells, pod_map


def make_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, FileResponse
    app = FastAPI(title="persona map")
    threading.Thread(target=lambda: [M.prior(p) for p in M.PERSONAS], daemon=True).start()   # warm cache

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (HERE / "index.html").read_text()

    @app.get("/api/meta")
    def meta():
        return {"personas": {k: {kk: v for kk, v in p.items()} for k, p in M.PERSONAS.items()},
                "clues": M.CLUES, "classes": M.CLASSES, "n": M.N, "cell_m": M.CELL, "half_m": M.HALF,
                "lkp": CFG["lkp"], "floor_anchor": CFG["floor_anchor"], "features": M.META}

    _osm = {}

    @app.get("/api/osm")
    def osm():
        if not _osm:
            o = json.loads((HERE / "osm_features.json").read_text())

            def simp(line, tol=8.0):
                pts = [ll2en(a, b) for a, b in line]; out = [pts[0]]
                for p in pts[1:]:
                    if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= tol:
                        out.append(p)
                if out[-1] != pts[-1]: out.append(pts[-1])
                return [[round(x), round(y)] for x, y in out]
            for k in ("road", "trail", "water", "waterline"):
                _osm[k] = [simp(l) for l in o[k]]
            _osm["building"] = [[round(v) for v in ll2en(a, b)] for a, b in o["building"]]
        return _osm

    @app.get("/api/state")
    def state(persona: str = "child_autistic"):
        if persona not in M.PERSONAS:
            raise HTTPException(404, "unknown persona")
        pr, post, cv, cl, mass, captured, dog, cells, pod_map = compute(persona)
        tops = M.top_cells(post, cl, 10)
        for t in tops:
            t["lat"], t["lon"] = en2ll(t["e"], t["n"])
            t["cv"] = round(float(cv[t["r"], t["c"]]), 2)
        p = M.PERSONAS[persona]
        return {"persona": persona, "prior": b64(pr), "post": b64(post), "cv": b64(cv),
                "pod": b64(pod_map) if pod_map is not None else None,
                "class_mass_pct": mass, "find_pct": p["find"], "verified": p["verified"], "source": p["source"],
                "note": p["note"], "top": tops, "clues": clues, "dog": dog,
                "probability_captured": captured, "max_post": float(post.max()), "max_prior": float(pr.max())}

    @app.post("/api/clue")
    def add_clue(d: dict):
        t = d.get("type")
        if t not in M.CLUES:
            raise HTTPException(422, "unknown clue type")
        if "lat" in d and "lon" in d:
            e, n = ll2en(float(d["lat"]), float(d["lon"]))
        elif "e" in d and "n" in d:
            e, n = float(d["e"]), float(d["n"])
        else:
            raise HTTPException(422, "need lat/lon or e/n")
        if abs(e) > M.HALF or abs(n) > M.HALF:
            raise HTTPException(422, "outside the 20 km grid")
        c = {"i": len(clues), "type": t, "label": M.CLUES[t]["label"], "e": e, "n": n,
             "lat": en2ll(e, n)[0], "lon": en2ll(e, n)[1], "note": str(d.get("note", ""))[:300],
             "operator": str(d.get("operator", "operator"))[:64], "t": time.time(), "active": True,
             "prov": M.CLUES[t]["prov"], "proposed_by": d.get("proposed_by")}
        for k in ("hours_ago", "ce_m", "pod", "radius_m"):
            if d.get(k) not in (None, ""):
                c[k] = float(d[k])
        if t == "searched_no_find" and "pod" not in c:
            # exponential model with Koester 2020 sweep width
            W = 22.0 if d.get("night") else 64.0
            L = float(d.get("track_m", 2000)); A = math.pi * c.get("radius_m", 200) ** 2
            c["pod"] = round(1 - math.exp(-W * L / A), 3); c["pod_calc"] = f"1-exp(-{W}·{L:.0f}/{A:.0f})"
        if d.get("photo_b64"):
            ph = HERE / "clue_photos"; ph.mkdir(exist_ok=True)
            raw = base64.b64decode(d["photo_b64"].split(",")[-1])[:8_000_000]
            fn = ph / f"clue_{c['i']:03d}.jpg"; fn.write_bytes(raw); c["photo"] = fn.name
            import hashlib; c["photo_sha256"] = hashlib.sha256(raw).hexdigest()
        with lock:
            clues.append(c); CLUES_F.write_text(json.dumps(clues, indent=1))
        c["chained"] = chain("clue_added", {k: v for k, v in c.items() if k != "chained"})
        return c

    @app.post("/api/clue/{i}/toggle")
    def toggle(i: int):
        with lock:
            if not 0 <= i < len(clues):
                raise HTTPException(404)
            clues[i]["active"] = not clues[i]["active"]; CLUES_F.write_text(json.dumps(clues, indent=1))
            c = clues[i]
        chain("clue_toggled", {"i": i, "active": c["active"]})
        return c

    @app.post("/api/persona")
    def persona(d: dict):
        chain("persona_selected", {"persona": d.get("persona"), "operator": d.get("operator", "")})
        return {"ok": True}

    @app.post("/api/propose")
    def propose(d: dict):
        """Ask Qwen3-VL (:8002) for a clue type. Advisory only: the operator picks the type."""
        img = d.get("photo_b64", "")
        if not img:
            raise HTTPException(422, "photo_b64 required")
        if not img.startswith("data:"):
            img = "data:image/jpeg;base64," + img
        types = ", ".join(M.CLUES)
        body = {"model": "qwen3-vl", "max_tokens": 120, "temperature": 0,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": img}},
                    {"type": "text", "text": f"Search and rescue clue triage. Choose ONE clue type from [{types}] for this photo and give a one-line reason. Answer as JSON: {{\"type\":...,\"reason\":...}}. If unsure, type=null."}]}]}
        try:
            models = json.loads(urllib.request.urlopen("http://127.0.0.1:8002/v1/models", timeout=2).read())
            body["model"] = models["data"][0]["id"]
            req = urllib.request.Request(VLM, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
            out = json.loads(urllib.request.urlopen(req, timeout=30).read())["choices"][0]["message"]["content"]
            import re
            m = re.search(r"\{.*\}", out, re.S)
            j = json.loads(m.group(0)) if m else {"type": None, "reason": out[:200]}
            if j.get("type") not in M.CLUES: j["type"] = None
            return {"available": True, "model": body["model"], **j, "advisory": "operator confirms the type"}
        except Exception as e:
            return {"available": False, "type": None, "reason": f"VLM on :8002 not reachable ({type(e).__name__}); pick the type by hand"}

    @app.get("/api/contacts")
    def contacts():
        try:
            return json.loads(urllib.request.urlopen(FUSION + "/contacts", timeout=1.5).read())
        except Exception:
            return []

    @app.get("/ortho.png")
    def ortho():
        return FileResponse(Path.home() / "forge/rescuebase-forge/data/ortho.png")

    @app.get("/api/ortho_bounds")
    def ortho_bounds():
        b = json.loads((Path.home() / "forge/rescuebase-forge/data/bounds.json").read_text())["bounds"]
        (s, w), (n, e) = b
        return {"sw_en": ll2en(s, w), "ne_en": ll2en(n, e)}

    @app.get("/health")
    def health():
        return {"ok": True, "warm": len(M._cache), "clues": len(clues)}

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(make_app(), host="0.0.0.0", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8143, log_level="warning")
