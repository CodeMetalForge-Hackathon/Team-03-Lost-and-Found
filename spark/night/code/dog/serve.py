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


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8141, log_level="warning")
