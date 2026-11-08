"""File-drop inbox shared by every sensor: night/inbox/<t>_<sensor>_<rand>.json
Schema: {t, sensor, kind, position:{x,y}|{lat,lon}, confidence, clip_path, extra?}"""
from __future__ import annotations
import json, os, time, uuid
from pathlib import Path

INBOX = Path(os.environ.get("NIGHT_INBOX", Path(__file__).resolve().parent.parent / "inbox"))


def emit(sensor: str, kind: str, confidence: float, position: dict | None = None,
         clip_path: str | None = None, t: float | None = None, extra: dict | None = None) -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    t = time.time() if t is None else float(t)
    if not (0.0 <= float(confidence) <= 1.0):
        raise ValueError("confidence must be in [0,1]")
    rec = {"t": t, "sensor": sensor, "kind": kind, "position": position or {},
           "confidence": round(float(confidence), 4), "clip_path": clip_path}
    if extra:
        rec["extra"] = extra
    name = f"{t:.3f}_{sensor}_{uuid.uuid4().hex[:6]}.json"
    tmp = INBOX / ("." + name)
    tmp.write_text(json.dumps(rec))
    tmp.rename(INBOX / name)          # atomic so the fuser never reads half a file
    return INBOX / name
