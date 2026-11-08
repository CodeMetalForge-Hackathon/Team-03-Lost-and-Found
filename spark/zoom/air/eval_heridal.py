"""Precision/recall of sliced detections against the HERIDAL test labels (YOLO format, class 0 = person).
Usage: eval_heridal.py <images_dir> <labels_dir> <dets.json> [<dets2.json> ...] -> prints + writes ../heridal_eval.json
Matching: greedy by confidence, IoU >= 0.5 (also reported at 0.3, since HERIDAL boxes are 20–80 px). AP50 = all-point VOC."""
import sys, json
from pathlib import Path
import numpy as np
from PIL import Image

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy; u = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / u if u > 0 else 0

def load_gt(imgs, labs):
    gt = {}
    for p in sorted(Path(imgs).iterdir()):
        W, H = Image.open(p).size; g = []
        lf = Path(labs) / (p.stem + ".txt")
        if lf.exists():
            for ln in lf.read_text().split("\n"):
                if ln.strip():
                    c, x, y, w, h = map(float, ln.split()[:5])
                    g.append([(x-w/2)*W, (y-h/2)*H, (x+w/2)*W, (y+h/2)*H])
        gt[p.name] = g
    return gt

def evaluate(gt, dets, thr):
    recs = []
    for name, g in gt.items():
        ds = sorted(dets.get(name, []), key=lambda d: -d["conf"]); used = [False]*len(g)
        for d in ds:
            b = [d["x0"], d["y0"], d["x1"], d["y1"]]; best, bi = 0, -1
            for k, gg in enumerate(g):
                if not used[k]:
                    v = iou(b, gg)
                    if v > best: best, bi = v, k
            tp = best >= thr
            if tp: used[bi] = True
            recs.append((d["conf"], tp))
    npos = sum(len(g) for g in gt.values())
    recs.sort(key=lambda r: -r[0]); tps = np.cumsum([r[1] for r in recs]); fps = np.cumsum([not r[1] for r in recs])
    rec = tps / max(npos, 1); prec = tps / np.maximum(tps + fps, 1)
    mrec = np.concatenate([[0], rec, [1]]); mpre = np.concatenate([[0], prec, [0]])
    for i in range(len(mpre)-2, -1, -1): mpre[i] = max(mpre[i], mpre[i+1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]; ap = float(np.sum((mrec[idx+1]-mrec[idx]) * mpre[idx+1]))
    out = {"npos": npos, "AP": round(ap, 3)}
    for c in (0.25, 0.60):
        k = sum(1 for r in recs if r[0] >= c); tp = int(tps[k-1]) if k else 0
        out[f"conf{c:.2f}"] = {"P": round(tp/max(k,1), 3), "R": round(tp/max(npos,1), 3), "TP": tp, "FP": k-tp, "FN": npos-tp}
    return out

imgs, labs = sys.argv[1], sys.argv[2]; gt = load_gt(imgs, labs)
res = {}
for f in sys.argv[3:]:
    d = json.loads(Path(f).read_text()); meta = d.pop("__meta__", {})
    res[Path(f).stem] = {"weights": meta.get("weights"), "settings": {k: meta.get(k) for k in ("tile","overlap","imgsz")},
                         "iou0.5": evaluate(gt, d, 0.5), "iou0.3": evaluate(gt, d, 0.3), "n_images": len(gt)}
print(json.dumps(res, indent=1))
Path(__file__).resolve().parent.joinpath("heridal_eval_raw.json").write_text(json.dumps(res, indent=1))
