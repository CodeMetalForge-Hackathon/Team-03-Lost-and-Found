"""Sliced (SAHI-style) person detection with AerialPerson-YOLO26. Run with ~/forge/zoom/venv_u84/bin/python.

Usage: detect_air.py <weights.pt> <out.json> <img_or_dir> [...] [--conf 0.05] [--tile 640] [--overlap 0.2] [--imgsz 640]
Each image is cut into tile x tile windows (overlap fraction), each window is run at imgsz, boxes are shifted back
to full-res pixels and merged with class-agnostic NMS (IoU 0.5). Writes {image_name: [{x0,y0,x1,y1,conf}]} plus a
__meta__ entry (weights, settings, runtime). A low conf floor is kept so precision/recall can be swept afterwards.
"""
import sys, json, time, argparse
from pathlib import Path
import numpy as np
import torch, torchvision
from PIL import Image
from ultralytics import YOLO

Image.MAX_IMAGE_PIXELS = None


def windows(W, H, t, ov):
    st = max(1, int(t * (1 - ov)))
    xs = list(range(0, max(W - t, 0) + 1, st)); ys = list(range(0, max(H - t, 0) + 1, st))
    if xs[-1] + t < W: xs.append(max(W - t, 0))
    if ys[-1] + t < H: ys.append(max(H - t, 0))
    return [(x, y) for y in ys for x in xs]


def run(model, arr, t, ov, imgsz, conf, bs=32):
    H, W = arr.shape[:2]
    wins = windows(W, H, t, ov)
    boxes, scores = [], []
    for k in range(0, len(wins), bs):
        batch = [arr[y:y + t, x:x + t] for x, y in wins[k:k + bs]]
        batch = [b if b.shape[:2] == (t, t) else np.pad(b, ((0, t - b.shape[0]), (0, t - b.shape[1]), (0, 0))) for b in batch]
        rs = model.predict([b[..., ::-1] for b in batch], imgsz=imgsz, conf=conf, verbose=False, half=True)  # BGR in
        for (x, y), r in zip(wins[k:k + bs], rs):
            if r.boxes is None or len(r.boxes) == 0:
                continue
            b = r.boxes.xyxy.cpu().numpy(); b[:, [0, 2]] += x; b[:, [1, 3]] += y
            boxes.append(b); scores.append(r.boxes.conf.cpu().numpy())
    if not boxes:
        return []
    B = torch.tensor(np.concatenate(boxes)); S = torch.tensor(np.concatenate(scores))
    keep = torchvision.ops.nms(B, S, 0.5).numpy()
    return [{"x0": float(B[i, 0]), "y0": float(B[i, 1]), "x1": float(min(B[i, 2], W)), "y1": float(min(B[i, 3], H)), "conf": float(S[i])} for i in keep]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("weights"); ap.add_argument("out"); ap.add_argument("inputs", nargs="+")
    ap.add_argument("--conf", type=float, default=0.05); ap.add_argument("--tile", type=int, default=640)
    ap.add_argument("--overlap", type=float, default=0.2); ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--rgb_bands", default=None, help="for 4-band GeoTIFF: read with rasterio, use bands 1-3")
    a = ap.parse_args()
    files = []
    for p in map(Path, a.inputs):
        files += sorted(q for q in p.iterdir() if q.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif")) if p.is_dir() else [p]
    model = YOLO(a.weights)
    t0 = time.time(); out = {}
    for f in files:
        arr = np.asarray(Image.open(f).convert("RGB"))[..., ::-1].copy()   # to BGR, as ultralytics expects for arrays
        out[f.name] = run(model, arr, a.tile, a.overlap, a.imgsz, a.conf)
    out["__meta__"] = {"weights": a.weights, "tile": a.tile, "overlap": a.overlap, "imgsz": a.imgsz, "conf_floor": a.conf,
                       "n_images": len(files), "runtime_s": round(time.time() - t0, 1)}
    Path(a.out).write_text(json.dumps(out))
    print(json.dumps(out["__meta__"]), sum(len(v) for k, v in out.items() if k != "__meta__"), "boxes")


if __name__ == "__main__":
    main()
