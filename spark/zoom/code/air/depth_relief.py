"""Depth-Anything-V2-Small relative depth over a scene's level-1 tiles -> shaded relief PNG (toggleable 2.5D layer).
Usage: depth_relief.py <scene_tiles_dir> [--level 1]. Output <scene>/depth/relief.png + meta.json.
Relative monocular depth on a nadir orthophoto is NOT elevation; it is a shading cue only (labelled on screen)."""
import sys, json, argparse, time
from pathlib import Path
import numpy as np, torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation
ap = argparse.ArgumentParser(); ap.add_argument("scene"); ap.add_argument("--level", type=int, default=1); a = ap.parse_args()
sc = Path(a.scene); meta = json.loads((sc / "meta.json").read_text()); L = next(l for l in meta["levels"] if l["z"] == a.level)
mp = str(Path.home() / "models/Depth-Anything-V2-Small-hf"); t0 = time.time()
proc = AutoImageProcessor.from_pretrained(mp); model = AutoModelForDepthEstimation.from_pretrained(mp).cuda().eval()
D = np.zeros((L["h"], L["w"]), np.float32); A = np.zeros((L["h"], L["w"]), bool)
for p in (sc / str(a.level)).glob("*.webp"):
    i, j = map(int, p.stem.split("_")); im = Image.open(p).convert("RGBA"); al = np.asarray(im)[..., 3] > 0
    x = proc(images=im.convert("RGB"), return_tensors="pt").to("cuda")
    with torch.no_grad():
        d = model(**x).predicted_depth[0]
    d = torch.nn.functional.interpolate(d[None, None], size=(im.height, im.width), mode="bilinear")[0, 0].cpu().numpy()
    d = (d - d[al].mean()) / (d[al].std() + 1e-6) if al.any() else d * 0          # per-tile normalisation (relative only)
    D[j*512:j*512+im.height, i*512:i*512+im.width] = d; A[j*512:j*512+im.height, i*512:i*512+im.width] = al
gy, gx = np.gradient(D); sh = np.clip(0.75 + 0.25 * (-gx - gy) / (np.abs(gx).std() + np.abs(gy).std() + 1e-6), 0, 1)
rgb = (np.dstack([sh] * 3) * 255).astype(np.uint8); rgb[~A] = 255
(sc / "depth").mkdir(exist_ok=True); Image.fromarray(rgb).save(sc / "depth" / "relief.png")
(sc / "depth" / "meta.json").write_text(json.dumps({"model": "Depth-Anything-V2-Small", "level": a.level, "runtime_s": round(time.time() - t0, 1),
    "note": "relative monocular depth, normalised per 512 px tile, rendered as shading; not elevation"}))
print("ok", sc, round(time.time() - t0, 1), "s")
