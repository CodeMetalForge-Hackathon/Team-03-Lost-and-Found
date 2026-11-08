"""Perch-and-listen demo server on :8142. /api/results = tag.py output; /api/tag/{clip} re-runs
PANNs + AST on the GPU for that clip right now (models load on first call)."""
from __future__ import annotations
import json, sys, threading, time
from pathlib import Path
import numpy as np, soundfile as sf, librosa
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
app = FastAPI(title="perch")
_m = {}; _lock = threading.Lock()


def models():
    with _lock:
        if not _m:
            from audio_presence import PannsTagger, AstTagger
            _m["panns"] = PannsTagger("cuda"); _m["ast"] = AstTagger("cuda")
    return _m


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "demo.html").read_text()


@app.get("/api/results")
def results():
    return json.loads((HERE / "results.json").read_text())


def _clip(name):
    p = (HERE / "clips" / name).resolve()
    if p.parent != (HERE / "clips").resolve() or not p.exists():
        raise HTTPException(404)
    return p


@app.get("/clips/{name}")
def clip(name: str):
    return FileResponse(_clip(name), media_type="audio/wav")


@app.get("/api/tag/{name}")
def tag(name: str):
    """Live inference. Note: clips on disk are peak-normalised for listening; tags from tag.py
    (results.json) were computed on raw levels. Both are shown; they agree on the HV contrast."""
    from audio_presence import presence, top_k
    m = models(); t = time.time()
    x, fs = sf.read(str(_clip(name)), dtype="float32")
    x32 = librosa.resample(x, orig_sr=fs, target_sr=32000)
    ps = m["panns"].scores(x32[None])[0]; asr = m["ast"].scores(x[None])[0]
    p_hv, p_hnv = presence(ps[None], m["panns"].labels, m["panns"].map)
    a_hv, a_hnv = presence(asr[None], m["ast"].labels, m["ast"].map)
    return {"clip": name, "ms": round((time.time() - t) * 1000),
            "panns": {"top": top_k(ps, m["panns"].labels, 5), "p_hv": round(float(p_hv[0]), 3)},
            "ast": {"top": top_k(asr, m["ast"].labels, 5), "p_hv": round(float(a_hv[0]), 3)}}


@app.post("/api/emit")
def emit(d: dict):
    """Operator sends a perched detection to the fusion inbox as acoustic_hv at the configured perch point.
    Confidence = the stored P(HV) for that clip (max of PANNs, AST) from results.json."""
    sys.path.insert(0, str(HERE.parent / "fusion"))
    import inbox
    res = json.loads((HERE / "results.json").read_text())
    name = str(d.get("clip", ""))
    hit = next((c for e in res["clips"] for c in e["conditions"] if c["clip"] == name), None)
    if hit is None:
        raise HTTPException(404, "unknown clip")
    p = max(hit["panns"]["p_hv"], hit["ast"]["p_hv"])
    cfg = json.loads((HERE.parent / "config.json").read_text()); pp = cfg["perch_point"]
    f = inbox.emit("perch1", "acoustic_hv", p, {"lat": pp["lat"], "lon": pp["lon"]}, str(HERE / "clips" / name),
                   extra={"condition": hit["condition"], "panns_top": hit["panns"]["top"][0][0], "dataset": "DroneAudioSet (recorded)"})
    return {"queued": f.name, "confidence": p, "position": pp}


@app.get("/health")
def health():
    return {"ok": True, "models_loaded": bool(_m)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8142, log_level="warning")
