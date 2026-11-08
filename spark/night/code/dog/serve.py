"""Dog replay server on :8141. Serves replay.html, the run list, layers.json and the overhead video."""
from __future__ import annotations
import json, sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "data/dog"
app = FastAPI(title="dog replay")


def _run(name: str) -> Path:
    p = (RUNS / name).resolve()
    if p.parent != RUNS.resolve() or not (p / "layers.json").exists():
        raise HTTPException(404, "no such processed run")
    return p


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "replay.html").read_text()


@app.get("/api/runs")
def runs():
    out = []
    for p in sorted(RUNS.glob("*/layers.json")):
        d = json.loads(p.read_text())
        out.append({"name": p.parent.name, "synthetic": d.get("synthetic", False)})
    out.sort(key=lambda r: (r["synthetic"], r["name"]))   # real runs first
    return out


@app.get("/api/run/{name}/layers")
def layers(name: str):
    return FileResponse(_run(name) / "layers.json", media_type="application/json")


@app.get("/api/run/{name}/video")
def video(name: str):
    p = _run(name) / "overhead.mp4"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="video/mp4")


DOGEYE_FILES = {"replay.mp4": "video/mp4", "intel.md": "text/markdown; charset=utf-8", "topdown.png": "image/png",
                "dogseye.png": "image/png", "replay.html": "text/html; charset=utf-8"}


DOGEYE_OUT = HERE.parent / "dogeye/out"     # read-only; independent of data/dog (never feeds map, AAR or scenario)


@app.get("/api/dogeye")
def dogeye_list():
    """Every dog's-eye reconstruction under night/dogeye/out/ that has a legs.json."""
    out = []
    for d in sorted(DOGEYE_OUT.glob("*/legs.json")):
        try:
            m = json.loads(d.read_text())
        except Exception:
            continue
        sol = "room_prior" if "room_prior" in m.get("solutions", {}) else "sensor_only"
        out.append({"name": d.parent.name, "run": m.get("run"), "duration_s": m.get("duration_s"),
                    "legs": len(m.get("legs", [])), "headings": sol,
                    "files": [f for f in DOGEYE_FILES if (d.parent / f).exists()]})
    return out


@app.get("/api/dogeye/{name}/{fname}")
def dogeye_file(name: str, fname: str):
    if fname not in DOGEYE_FILES:
        raise HTTPException(404)
    root = DOGEYE_OUT.resolve(); p = (root / name / fname).resolve()
    if p.parent.parent != root or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type=DOGEYE_FILES[fname])


@app.get("/api/scale")
def scale():
    """Floor -> search-map scaling used by fusion and the map (config.json floor_anchor.scale)."""
    cfg = json.loads((HERE.parent / "config.json").read_text())
    k = float(cfg["floor_anchor"].get("scale", 1.0))
    map_cell = 50.0      # map/model.py CELL
    return {"scale": k, "map_cell_m": map_cell, "floor_cell_m_equiv": map_cell / k}


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8141, log_level="warning")
