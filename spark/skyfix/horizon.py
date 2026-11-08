"""Horizon (skyline) extraction from a daytime photo -> horizon elevation angle per image column.

Primary: SAM 2 (hiera-small weights on disk at ~/models/sam2-hiera-small, loaded via transformers) prompted with
points along the top of the frame (top-centre first). Fallback: dynamic-programming max-gradient path (a
classic sky/ground split: one row per column, smoothness-constrained). The sky region is the connected
component touching the top edge; horizon row per column = first non-sky row from the top.
"""
from __future__ import annotations
import math, pathlib, threading
import numpy as np
from PIL import Image

SAM_DIR = pathlib.Path.home() / "models" / "sam2-hiera-small"
_SAM = {}
_LOCK = threading.Lock()


def _sam():
    with _LOCK:
        if "m" not in _SAM:
            import torch
            from transformers import Sam2Model, Sam2Processor
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            _SAM["proc"] = Sam2Processor.from_pretrained(str(SAM_DIR))
            _SAM["m"] = Sam2Model.from_pretrained(str(SAM_DIR)).to(dev).eval()
            _SAM["dev"] = dev
    return _SAM["m"], _SAM["proc"], _SAM["dev"]


def sam_sky_mask(img: Image.Image) -> np.ndarray:
    """Boolean sky mask (True = sky)."""
    import torch
    m, proc, dev = _sam()
    w, h = img.size
    pts = [[[[0.5 * w, 0.03 * h], [0.15 * w, 0.03 * h], [0.85 * w, 0.03 * h]]]]
    lab = [[[1, 1, 1]]]
    inp = proc(images=img, input_points=pts, input_labels=lab, return_tensors="pt").to(dev)
    with torch.inference_mode():
        out = m(**inp, multimask_output=True)
    masks = proc.post_process_masks(out.pred_masks.cpu(), inp["original_sizes"])[0][0]  # (3, H, W)
    # union of the 3 multimask outputs: chosen on the CH1 DEV split (median horizon MAE 2.39 px vs 2.93 px for
    # best-IoU; clouds often split the sky into separate masks)
    return masks.numpy().astype(bool).any(0)


def dp_horizon_rows(img: Image.Image, work_w: int = 320, max_step: int = 2) -> np.ndarray:
    """Fallback: per-column horizon row via DP over a vertical-gradient cost (sky above is bright/blue/smooth)."""
    from scipy.ndimage import gaussian_filter, sobel
    W, H = img.size
    s = work_w / W
    small = np.asarray(img.convert("RGB").resize((work_w, max(8, int(H * s))), Image.BILINEAR), np.float32) / 255.0
    g = small.mean(2)
    blue = small[..., 2] - small[..., 0]
    f = gaussian_filter(g, 1.2) + 0.5 * gaussian_filter(blue, 1.2)
    gy = -sobel(f, axis=0)  # positive where it gets darker going down (sky -> ground)
    gy = np.clip(gy, 0, None) + 0.3 * np.abs(sobel(gaussian_filter(g, 1.0), axis=1))
    hh, ww = gy.shape
    # prior: sky region should be smooth -> penalise rows whose region above has high texture
    tex = gaussian_filter(np.abs(sobel(g, axis=0)) + np.abs(sobel(g, axis=1)), 2)
    cum_tex = np.cumsum(tex, 0) / (np.arange(1, hh + 1)[:, None])
    score = gy - 0.5 * cum_tex
    acc = score[:, 0].copy()
    back = np.zeros((hh, ww), np.int32)
    for x in range(1, ww):
        best = np.full(hh, -1e9); arg = np.zeros(hh, np.int32)
        for dy in range(-max_step, max_step + 1):
            sh = np.roll(acc, dy)
            if dy > 0: sh[:dy] = -1e9
            elif dy < 0: sh[dy:] = -1e9
            better = sh > best
            best[better] = sh[better]; arg[better] = (np.arange(hh) - dy)[better]
        acc = best + score[:, x]; back[:, x] = arg
    rows = np.zeros(ww, np.int32); rows[-1] = int(acc.argmax())
    for x in range(ww - 1, 0, -1):
        rows[x - 1] = back[rows[x], x]
    xs = (np.arange(W) + 0.5) * s - 0.5
    return np.interp(xs, np.arange(ww), rows) / s


def rows_from_sky_mask(sky: np.ndarray) -> np.ndarray:
    """First non-sky row per column, using only sky connected to the top edge."""
    from scipy.ndimage import label
    lab, n = label(sky)
    band = lab[: max(3, sky.shape[0] // 50)]
    top = np.unique(band[band > 0])
    conn = np.isin(lab, top) if len(top) else np.zeros_like(sky)
    H = sky.shape[0]
    b = max(3, H // 50)
    nonsky = ~conn
    top_ground = sky[:b].mean(0) < 0.5  # terrain reaches the top edge in this column: horizon is above the frame
    nonsky[:b] = False  # tolerate a few border rows the mask dropped
    first = np.where(nonsky.any(0), nonsky.argmax(0), H).astype(np.float64)
    first[top_ground] = 0.0  # -> marked invalid downstream (rows <= 1)
    return first


def gt_rows(mask_path) -> np.ndarray:
    m = np.asarray(Image.open(mask_path).convert("L")) < 128  # CH1: sky = black
    return rows_from_sky_mask(m)


def rows_to_angles(rows: np.ndarray, focal_px: float, width: int, height: int):
    """Column azimuth offset (deg, + right of centre) and horizon elevation (deg, relative to optical axis)."""
    x = np.arange(width) + 0.5 - width / 2
    y = height / 2 - (np.asarray(rows) + 0.5)
    az = np.degrees(np.arctan2(x, focal_px))
    el = np.degrees(np.arctan2(y, np.hypot(x, focal_px)))
    return az, el


def extract(img: Image.Image, method: str = "auto"):
    """Returns (rows per column, method used, sky mask or None)."""
    img = img.convert("RGB")
    if method in ("auto", "sam"):
        try:
            sky = sam_sky_mask(img)
            rows = rows_from_sky_mask(sky)
            if np.mean(rows >= img.size[1] - 1) < 0.5 and np.mean(rows <= 0) < 0.5:
                return rows, "sam2", sky
        except Exception as e:  # noqa: BLE001 - fallback is the point
            if method == "sam":
                raise
            print("SAM2 failed, using DP fallback:", repr(e)[:200])
    return dp_horizon_rows(img), "dp_gradient", None
