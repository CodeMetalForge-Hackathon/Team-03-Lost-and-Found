"""results/course.png from results/course.json: offline vector base from pack/buildings.json (OSM raster tiles were blocked), 60 State outline, 56.9 deg cones, numbered fixes,
arrows, and a strip of the four frames (EXIF-stripped 1200 px copies) with the confirmed landmark taps drawn."""
import json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
C = Path(__file__).resolve().parent; R = json.loads((C / "results/course.json").read_text())
import course as K
Z = 17; T = 256
def px(lat, lon):
    n = 2 ** Z; r = math.radians(lat); return (lon + 180) / 360 * n * T, (1 - math.asinh(math.tan(r)) / math.pi) / 2 * n * T
cx, cy = px(42.3592, -71.0564); W, H = 900, 900; S = 2.0                 # 2x upsampled z17 for legibility
ox, oy = cx - W / S / 2, cy - H / S / 2
m = Image.new("RGB", (W, H), (236, 233, 226)); g = ImageDraw.Draw(m, "RGBA")
P = lambda lat, lon: ((px(lat, lon)[0] - ox) * S, (px(lat, lon)[1] - oy) * S)
mpp = 156543.03 * math.cos(math.radians(42.3592)) / 2 ** Z / S
for b in json.loads((C / "pack/buildings.json").read_text())["buildings"]:          # vector base map from the pack (offline)
    q = [P(a, o) for a, o in b["ring"]]
    if any(0 <= x <= W and 0 <= y <= H for x, y in q):
        sh = int(max(110, 215 - b["h"] * 0.5)); g.polygon(q, fill=(sh, sh, sh + 8), outline=(120, 120, 130))
ring = [P(a, o) for a, o in K.B155["ring"]]; g.polygon(ring, outline=(0, 90, 255, 255), fill=(0, 90, 255, 40)); g.line(ring, fill=(0, 90, 255), width=3)
cols = [(230, 60, 60), (240, 150, 0), (40, 170, 70), (150, 60, 220)]
try:
    fnt = ImageFont.truetype("DejaVuSans-Bold.ttf", 22); fs = ImageFont.truetype("DejaVuSans.ttf", 15)
except Exception:
    fnt = fs = ImageFont.load_default()
pts = []
for s, c in zip(R["shots"], cols):
    x, y = P(s["post_gate"]["lat"], s["post_gate"]["lon"]); pts.append((x, y)); hd = s["post_gate"]["heading_deg"]; L = 260 / mpp * mpp / mpp * 0 + 230
    a1, a2 = math.radians(hd - 28.45), math.radians(hd + 28.45)
    g.polygon([(x, y), (x + L * math.sin(a1), y - L * math.cos(a1)), (x + L * math.sin(a2), y - L * math.cos(a2))], fill=c + (55,), outline=c + (200,))
    x0, y0 = P(s["pre_gate"]["lat"], s["pre_gate"]["lon"]); g.line([(x0, y0), (x, y)], fill=c + (160,), width=2); g.ellipse([x0 - 4, y0 - 4, x0 + 4, y0 + 4], outline=c, width=2)
for (a, b), c in zip(zip(pts, pts[1:]), cols):
    g.line([a, b], fill=(255, 255, 255), width=4); ang = math.atan2(b[1] - a[1], b[0] - a[0])
    g.polygon([b, (b[0] - 14 * math.cos(ang - 0.4), b[1] - 14 * math.sin(ang - 0.4)), (b[0] - 14 * math.cos(ang + 0.4), b[1] - 14 * math.sin(ang + 0.4))], fill=(255, 255, 255))
for (x, y), s, c in zip(pts, R["shots"], cols):
    g.ellipse([x - 13, y - 13, x + 13, y + 13], fill=c, outline=(255, 255, 255), width=2); g.text((x - 7, y - 12), s["shot"][1], fill=(255, 255, 255), font=fnt)
g.rectangle([0, 0, W, 58], fill=(0, 0, 0, 170))
g.text((8, 4), f"Course: 60 State St, 4 shots, {R['total_s']:.0f} s, {R['direction']} {'-'.join(R['faces'])} · joint h {R['joint_h_m']} m → floor {R['floor_est']} (truth 14)", fill=(255, 255, 255), font=fs)
g.text((8, 24), "filled: post-gate fix + 56.9° cone; hollow: pre-gate fix. Base: OSM building footprints from the pack (vector, offline).", fill=(220, 220, 220), font=fs)
g.text((8, H - 20), "© OpenStreetMap contributors (footprints, ODbL)", fill=(30, 30, 30), font=fs)
strip = []
for s, c in zip(R["shots"], cols):
    im = Image.open(C / f"shots_web/{s['file']}.jpg").convert("RGB"); d = ImageDraw.Draw(im); w, h = im.size
    for o in s["obs"]:
        if o["kind"] == "skip":
            continue
        x = o["x"] * w
        if o["y"] is None:
            d.line([(x, 0), (x, h)], fill=c, width=3)
        else:
            y = o["y"] * h; d.ellipse([x - 12, y - 12, x + 12, y + 12], outline=c, width=4)
        d.text((x + 8, (o["y"] or 0.03) * h - 22), o["label"][:26], fill=(255, 255, 0), font=fs)
    d.rectangle([0, h - 34, w, h], fill=(0, 0, 0)); d.text((8, h - 28), f"{s['shot']} {s['time'][11:19]} {s['gate']['face']} face, hdg {s['post_gate']['heading_deg']:.0f}°", fill=(255, 255, 255), font=fnt)
    im.thumbnail((450, 600)); strip.append(im)
out = Image.new("RGB", (W + 2 * 450, max(H, 1200)), (14, 17, 22)); out.paste(m, (0, 0))
for i, im in enumerate(strip):
    out.paste(im, (W + (i % 2) * 450, (i // 2) * 600))
out.save(C / "results/course.png"); print(out.size)
