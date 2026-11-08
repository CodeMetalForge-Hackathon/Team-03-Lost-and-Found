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
GET  /api/nba               Next Best Action on the current COP (hint only; never auto-tasks)
POST /api/nba/decision      {decision: accept|dismiss, operator, nba} -> forwarded to fusion (chained there)
POST /api/nba/mark          fusion tells the map a decision was chained (cell leaves the suggestion pool)
GET  /api/drone             real drone track (ODM Aukerman shots) + ortho bounds for the reveal replay
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
import cop as C  # noqa: E402

CFG = json.loads((NIGHT / "config.json").read_text())
FUSION = "http://127.0.0.1:8140"
VLM = "http://127.0.0.1:8002/v1/chat/completions"
CLUES_F = HERE / "clues.json"
STATE_F = HERE / "state.json"
R = 6371008.8
LAT0, LON0 = CFG["lkp"]["lat"], CFG["lkp"]["lon"]
lock = threading.Lock()
clues: list[dict] = json.loads(CLUES_F.read_text()) if CLUES_F.exists() else []
NBA_F = HERE / "nba.json"
nba_log: list[dict] = json.loads(NBA_F.read_text()) if NBA_F.exists() else []
GRID = C.Grid(M.N, M.CELL, M.HALF, LAT0, LON0)
TRACK = json.loads((HERE / "drone_track.json").read_text()) if (HERE / "drone_track.json").exists() else {"shots": []}
SKYFIX_COT = Path.home() / "forge/skyfix/cot"          # read-only
DRONE_T = {"t": None}                                   # replay progress (s); None = drone not flown yet
LAST = {}


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
            "cell_map_m": C["cell_m"] * k, "scale": k, "floor_cell_m": C["cell_m"], "map_cell_m": M.CELL,
            "cells_match": abs(C["cell_m"] * k - M.CELL) < 1e-6,
            "sector_m": [round((x1 - x0) * k), round((y1 - y0) * k)]}, cells


def b64(a):
    return base64.b64encode(np.ascontiguousarray(a, dtype=np.float32).tobytes()).decode()


def detections():
    try:
        return json.loads(urllib.request.urlopen(FUSION + "/detections?limit=5000", timeout=1.5).read())
    except Exception:
        return []


def sparse(a, rel=1e-4):
    if a is None or not np.any(a > 0):
        return None
    idx = np.flatnonzero(a > a.max() * rel).astype(np.int32)
    return {"idx": base64.b64encode(idx.tobytes()).decode(), "val": b64(a.ravel()[idx]), "max": float(a.max())}


def compute(persona, enabled=None):
    """COP = normalise((prior x positive-clue LRs) + sensor fields) x (1 - POD dog/team/drone)."""
    dog, cells = dog_coverage()
    pr, cv, cl, mass = M.prior(persona)
    with lock:
        cl_list = [c for c in clues if c.get("active", True)]
    base = pr.copy()
    for c in cl_list:
        if c["type"] != "searched_no_find":
            base = base * M.clue_lr(c)
    base = base / base.sum()
    team = [{"e": c["e"], "n": c["n"], "radius_m": c.get("radius_m", 200), "pod": c.get("pod", 0.5)}
            for c in cl_list if c["type"] == "searched_no_find"]
    pods = {"dog": M.coverage_pod(cells) if cells else None,
            "team": C.disk_pod(team, GRID) if team else None,
            "drone": C.drone_pod(TRACK["shots"], DRONE_T["t"], GRID, CFG["coverage"]["drone_pod_per_pass"])
            if DRONE_T["t"] is not None else None}
    pod = C.combine_pod(*pods.values())
    fl = [f for f in (C.event_field(d, GRID, CFG, floor_to_en) for d in detections()) if f]
    sky = C.skyfix_fixes(SKYFIX_COT, GRID, CFG)
    fl += sky
    raw_layers = C.sum_fields(fl, GRID.E.shape)
    layers, capinfo = C.cap_layers(raw_layers, CFG["fields"].get("source_cap_frac", 0.5), 1.0)   # base is normalised to 1
    copm = C.cop(base, layers, pod, enabled)
    captured = float((base * pod).sum()) if pod is not None else 0.0
    STATE_F.write_text(json.dumps({"persona": persona, "probability_captured": round(captured, 5),
                                   "dog_run": dog and dog["run"], "n_clues": len(cl_list), "t": time.time()}))
    summ = {}
    for f in fl:
        d = summ.setdefault(f["source"], {"source": f["source"], "label": C.SOURCE_LABEL[f["source"]], "n": 0,
                                          "mass": 0.0, "mass_on_grid": 0.0, "kernels": set()})
        d["n"] += 1; d["mass"] += f["mass"]; d["mass_on_grid"] += f["mass_on_grid"]; d["kernels"].add(f["kernel"].split(" (")[0])
    for d in summ.values():
        d["kernels"] = sorted(d["kernels"])[:3]; d["mass"] = round(d["mass"], 3); d["mass_on_grid"] = round(d["mass_on_grid"], 3)
        ci = capinfo[d["source"]]; d["capped_mass"] = ci["capped"]; d["cap"] = ci["cap"]; d["cap_scale"] = ci["scale"]
    tasked = {tuple(x["nba"]["cell"]) for x in nba_log if x.get("nba") and x["nba"].get("cell")}
    nba = C.next_best_action(copm, pod, GRID, CFG, tasked)
    LAST.update({"persona": persona, "nba": nba, "t": time.time()})
    return dict(pr=pr, base=base, cv=cv, cl=cl, mass=mass, captured=captured, dog=dog, pods=pods, pod=pod,
                layers=layers, cop=copm, fields=list(summ.values()), sky=sky, nba=nba)


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
    def state(persona: str = "child_autistic", enabled: str | None = None, drone_t: float | None = None):
        if persona not in M.PERSONAS:
            raise HTTPException(404, "unknown persona")
        if drone_t is not None:
            DRONE_T["t"] = None if drone_t < 0 else float(drone_t)
        en = None if enabled in (None, "", "all") else set(enabled.split(","))
        S = compute(persona, en)
        tops = M.top_cells(S["cop"], S["cl"], 10)
        for t in tops:
            t["lat"], t["lon"] = en2ll(t["e"], t["n"])
            t["cv"] = round(float(S["cv"][t["r"], t["c"]]), 2)
        p = M.PERSONAS[persona]
        return {"persona": persona, "prior": b64(S["pr"]), "post": b64(S["base"]), "cop": b64(S["cop"]), "cv": b64(S["cv"]),
                "pod": b64(S["pod"]) if S["pod"] is not None else None,
                "pod_layers": {k: sparse(v) for k, v in S["pods"].items()},
                "field_layers": {k: sparse(v) for k, v in S["layers"].items()},
                "fields": S["fields"], "enabled": sorted(en) if en else "all",
                "field_cap": CFG["fields"].get("source_cap_frac", 0.5), "drone_pod_per_pass": CFG["coverage"]["drone_pod_per_pass"],
                "skyfix": {"n": len(S["sky"]), "on_grid": sum(1 for f in S["sky"] if f["mass_on_grid"] > 1e-3),
                           "dir": str(SKYFIX_COT)},
                "drone_t": DRONE_T["t"], "nba": S["nba"], "nba_log": nba_log[-20:],
                "class_mass_pct": S["mass"], "find_pct": p["find"], "verified": p["verified"], "source": p["source"],
                "note": p["note"], "top": tops, "clues": clues, "dog": S["dog"],
                "probability_captured": S["captured"]}

    @app.get("/api/nba")
    def nba(persona: str | None = None):
        compute(persona or LAST.get("persona", "child_autistic"))     # always fresh: decisions change the pool
        return {**LAST["nba"], "persona": LAST["persona"], "hint_only": True}

    @app.post("/api/nba/decision")
    def nba_decision(d: dict):
        """Forward to fusion, which chains the decision (and writes a waypoint CoT on accept)."""
        if d.get("decision") not in ("accept", "dismiss"):
            raise HTTPException(422, "decision must be accept or dismiss")
        if not str(d.get("operator", "")).strip():
            raise HTTPException(422, "operator id required")
        body = {"decision": d["decision"], "operator_id": str(d["operator"])[:64], "nba": d.get("nba") or LAST.get("nba"),
                "persona": LAST.get("persona")}
        try:
            req = urllib.request.Request(FUSION + "/nba/decision", data=json.dumps(body).encode(),
                                         headers={"content-type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=3).read())
        except Exception as e:
            raise HTTPException(503, f"fusion not reachable, decision NOT recorded ({type(e).__name__})")

    @app.post("/api/nba/mark")
    def nba_mark(d: dict):
        with lock:
            nba_log.append(d); NBA_F.write_text(json.dumps(nba_log, indent=1))
        return {"ok": True, "n": len(nba_log)}

    @app.get("/api/drone")
    def drone():
        b = json.loads((Path.home() / "forge/rescuebase-forge/data/bounds.json").read_text())["bounds"]
        (s_, w_), (n_, e_) = b
        return {"track": TRACK, "ortho": {"sw_en": ll2en(s_, w_), "ne_en": ll2en(n_, e_)}, "drone_t": DRONE_T["t"],
                "pod_per_pass": CFG["coverage"]["drone_pod_per_pass"]}

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
