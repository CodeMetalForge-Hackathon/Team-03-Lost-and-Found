"""Hazard chips over the NOAA mosaic with Qwen3-VL-4B (transformers, local weights). Captions are NOT detections.

Usage: captions.py <scene_tiles_dir> [--level 2] [--model ~/models/qwen3-vl-4b]
For each pyramid tile at the given level (~0.8 m/px, 512 px ≈ 400 m), ask for ONE short hazard caption from a closed
list, or "none". Writes <scene>/captions.json {chips:[{lat, lon, text, tile, raw}], note}. Load time is checked:
if the model takes > 300 s to load, the script exits and writes a note saying captions were skipped.
"""
import sys, json, time, argparse
from pathlib import Path
import torch
from PIL import Image

VOCAB = ["flooded road", "flooded structures", "collapsed structure", "roof damage", "debris field", "washed-out road",
         "downed trees", "sand overwash", "boats displaced", "intact neighborhood", "open water", "beach", "forest", "none"]
PROMPT = ("Aerial orthophoto tile, about 400 m across, seen from directly above. Is there CLEAR, unambiguous visible damage? "
          "Damage labels: flooded road, flooded structures, collapsed structure, roof damage, debris field, washed-out road, downed trees, "
          "sand overwash, boats displaced. If you are not sure, or the scene looks normal, answer with the land cover instead: "
          "intact neighborhood, open water, beach, forest, or none. Reply with one label only.")

ap = argparse.ArgumentParser(); ap.add_argument("scene"); ap.add_argument("--level", type=int, default=2)
ap.add_argument("--model", default=str(Path.home() / "models/qwen3-vl-4b")); a = ap.parse_args()
scene = Path(a.scene); meta = json.loads((scene / "meta.json").read_text())
t0 = time.time()
try:
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
    model = Qwen3VLForConditionalGeneration.from_pretrained(a.model, dtype=torch.bfloat16, device_map="cuda")
    proc = AutoProcessor.from_pretrained(a.model)
except Exception as e:
    (scene / "captions.json").write_text(json.dumps({"chips": [], "note": f"Qwen3-VL failed to load ({e.__class__.__name__}); captions skipped."}))
    sys.exit(0)
load_s = time.time() - t0
if load_s > 300:
    (scene / "captions.json").write_text(json.dumps({"chips": [], "note": f"Qwen3-VL took {load_s:.0f} s to load (> 300 s); captions skipped."}))
    sys.exit(0)
L = next(l for l in meta["levels"] if l["z"] == a.level); b = meta["bounds"]
dlon = (b["e"] - b["w"]) / L["w"]; dlat = (b["n"] - b["s"]) / L["h"]
chips = []; t1 = time.time()
for p in sorted((scene / str(a.level)).glob("*.webp")):
    i, j = map(int, p.stem.split("_")); im = Image.open(p).convert("RGBA")
    alpha = im.getchannel("A")
    if sum(alpha.histogram()[1:]) < 0.5 * im.width * im.height:     # mostly empty edge tile
        continue
    bg = Image.new("RGB", im.size, (0, 0, 0)); bg.paste(im, mask=alpha)
    msgs = [{"role": "user", "content": [{"type": "image", "image": bg}, {"type": "text", "text": PROMPT}]}]
    inp = proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=8, do_sample=False)
    raw = proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip().lower().rstrip(".")
    lab = next((v for v in VOCAB if v in raw), "none")
    cx = (i * 512 + im.width / 2); cy = (j * 512 + im.height / 2)
    chips.append({"tile": p.name, "lat": b["n"] - cy * dlat, "lon": b["w"] + cx * dlon, "text": lab, "raw": raw})
hazards = {"flooded road", "flooded structures", "collapsed structure", "roof damage", "debris field", "washed-out road",
           "downed trees", "sand overwash", "boats displaced"}
shown = [c for c in chips if c["text"] in hazards]
(scene / "captions.json").write_text(json.dumps({
    "chips": shown, "all": chips,
    "note": (f"Qwen3-VL-4B (local transformers, loaded in {load_s:.0f} s), one closed-vocabulary label per ~{512*L['m_per_px']:.0f} m tile, "
             f"greedy decoding. {len(shown)} hazard chips shown of {len(chips)} tiles captioned ({time.time()-t1:.0f} s). "
             "Unvalidated: a caption is a hint for the operator, never a detection.")}, indent=1))
print(len(chips), "tiles,", len(shown), "hazard chips, load", round(load_s), "s")
