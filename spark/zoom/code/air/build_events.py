"""Build the AIR event lists that the drone replay emits into the fusion inbox.

1. Real detections: every AerialPerson-YOLO26l box with conf >= 0.60 (the deployed gate) on the 77 Aukerman photos,
   georeferenced through ODM camera poses (dets/aukerman_geo.json), timed at the photo's capture time in the real
   flight (night/map/drone_track.json t_rel). sensor=aerial_rgb, kind=aerial_person. These are machine output: most are
   playground equipment (see aukerman_audit.json); the operator decides.
2. Victim pins (SIMULATED placement): the 5 highest-confidence HERIDAL true positives (IoU >= 0.5 with a label, conf >= 0.60,
   distinct photos, YOLO26l 1280->640 slicing). Each is shown at the position of an Aukerman photo spread through the
   flight (photo k*N/6), offset within that footprint by its pixel position (north-up assumed).
   sensor=aerial_rgb_sim, kind=aerial_person, extra.simulated_placement=true. Separate COP source so it can be unticked.
Writes air/air_events.json and air/victim_pins.json.
"""
import json, math
from pathlib import Path
from PIL import Image

Z = Path(__file__).resolve().parent.parent; A = Z / "air"; NIGHT = Path.home() / "forge/night"
R = 6371008.8
cfg = json.loads((NIGHT / "config.json").read_text()); lat0, lon0 = cfg["lkp"]["lat"], cfg["lkp"]["lon"]
track = json.loads((NIGHT / "map/drone_track.json").read_text())["shots"]
tmap = {s["file"]: s for s in track}
geo = json.loads((A / "dets/aukerman_geo.json").read_text())["dets"]
aud = {(x["img"], x["conf"]): x["audit"] for x in json.loads((A / "aukerman_audit.json").read_text())["items"]}
en2ll = lambda e, n: (lat0 + math.degrees(n / R), lon0 + math.degrees(e / (R * math.cos(math.radians(lat0)))))
events = []
for d in geo:
    if d["lat"] is None or d["img"] not in tmap:
        continue
    events.append({"t_rel": tmap[d["img"]]["t_rel"], "sensor": "aerial_rgb", "kind": "aerial_person", "confidence": round(d["conf"], 3),
                   "position": {"lat": d["lat"], "lon": d["lon"]},
                   "extra": {"detector": "AerialPerson-YOLO26l (AGPL-3.0)", "photo": d["img"], "georef": "ODM camera pose ray to ground plane",
                             "sigma_m": 15, "box_px": [round(d[k]) for k in ("x0", "y0", "x1", "y1")]}})
# HERIDAL TPs
def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    return i / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i)
H = json.loads((A / "dets/heridal_y26l_t1280.json").read_text()); H.pop("__meta__")
tps = []
for name, bs in H.items():
    im = A / "heridal/test/images" / name; W, Hh = Image.open(im).size
    lab = A / "heridal/test/labels" / (Path(name).stem + ".txt"); gts = []
    for ln in lab.read_text().split("\n") if lab.exists() else []:
        if ln.strip():
            c, x, y, w, h = map(float, ln.split()[:5]); gts.append([(x-w/2)*W, (y-h/2)*Hh, (x+w/2)*W, (y+h/2)*Hh])
    for b in bs:
        if b["conf"] >= 0.6 and any(iou([b["x0"], b["y0"], b["x1"], b["y1"]], g) >= 0.5 for g in gts):
            tps.append((b["conf"], name, b, W, Hh))
tps.sort(key=lambda x: -x[0]); seen, pick = set(), []
for t in tps:
    if t[1] not in seen:
        seen.add(t[1]); pick.append(t)
    if len(pick) == 5:
        break
pins = []
for k, (c, name, b, W, Hh) in enumerate(pick):
    sh = track[(k + 1) * len(track) // 6]
    fx, fy = ((b["x0"] + b["x1"]) / 2 / W - 0.5), ((b["y0"] + b["y1"]) / 2 / Hh - 0.5)
    e = sh["e"] + fx * sh["footprint_m"][0]; n = sh["n"] - fy * sh["footprint_m"][1]
    la, lo = en2ll(e, n)
    pin = {"lat": la, "lon": lo, "e": round(e, 1), "n": round(n, 1), "conf": round(c, 3), "heridal_photo": name, "shown_at_photo": sh["file"],
           "t_rel": sh["t_rel"], "label": "victim pin (georeferenced from SAR frames, simulated placement)",
           "crop_box_px": [round(b[q]) for q in ("x0", "y0", "x1", "y1")]}
    pins.append(pin)
    events.append({"t_rel": sh["t_rel"], "sensor": "aerial_rgb_sim", "kind": "aerial_person", "confidence": round(c, 3),
                   "position": {"lat": la, "lon": lo},
                   "extra": {"simulated_placement": True, "heridal_photo": name, "shown_at_photo": sh["file"], "sigma_m": 15,
                             "detector": "AerialPerson-YOLO26l (AGPL-3.0)", "ground_truth": "matches a HERIDAL person label (IoU >= 0.5)"}})
events.sort(key=lambda e: e["t_rel"])
(A / "air_events.json").write_text(json.dumps({"events": events, "n_real": sum(1 for e in events if e["sensor"] == "aerial_rgb"),
                                               "n_sim": len(pins)}, indent=1))
(A / "victim_pins.json").write_text(json.dumps({"pins": pins, "note": "HERIDAL test-split true positives (Croatia SAR photos) placed at Aukerman photo positions: SIMULATED placement."}, indent=1))
print(len(events), "events;", len(pins), "victim pins", [p["heridal_photo"] for p in pins])
