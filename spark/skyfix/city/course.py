"""COURSE MODE: multi-shot dead reckoning on one building from window photos (no GPS, no compass; clock + lens only).

Per shot: bearings phi = atan((px - cx) / f) (level camera, roll ignored); unknown (E, N, heading) by least squares over >= 3
observations: point landmarks (bearing to a lat/lon) and building edges (bearing to the left/right silhouette vertex of an OSM
footprint as seen from the current camera, or a named corner). Initial guess by grid search, then Gauss-Newton (resect.wrap,
resect.Local reused). GLAZING GATE: snap to the 60 State outline (pack/buildings.json, h=155) on the face segment whose outward
normal is within +-35 deg of the heading; heading re-fitted with the position fixed. Height: (a) tallest far landmark vs the sea
horizon with dip = 0.0293 deg x sqrt(h), iterated; (b) each known-height landmark alone (level camera where there is no horizon).
Joint h = median of all estimates; floor = round((h - 6) / 3.85) + 1 (60 State: 155 m, 38 floors, ~6 m lobby).
Ground truth (results/course_truth.json) is used ONLY for scoring after the solve.
Usage: ~/forge/.venv/bin/python course.py   -> results/course.json, results/course.png
"""
import json, math
from pathlib import Path
import numpy as np
import resect as R

C = Path(__file__).resolve().parent
W_IMG, H_IMG, F = 4284, 5712, 3950.0          # portrait upright frame; f_px = 0.922 x 4284 (24 mm equiv, 56.9 deg HFOV)
CX, CY = W_IMG / 2, H_IMG / 2
LAT0, LON0 = 42.3592, -71.0564                 # local frame origin (any downtown point; not a prior)
LOC = R.Local(LAT0, LON0)
GROUND_CAM = 5.3                               # USGS 3DEP at 60 State St (EPQS cache)
FP = json.loads((C / "data/course_footprints.json").read_text())
LMP = {l["name"]: l for l in json.loads((C / "pack/landmarks.json").read_text())["landmarks"]}


def pk(name):
    l = LMP[name]; return l["lat"], l["lon"]


def osh_east():
    r = np.array(FP["29608515"]["ring"]); i = r[:, 1].argmax(); return float(r[i, 0]), float(r[i, 1])


def stock_facade():                            # midpoint of the State St (north) edge of the Exchange Place footprint
    r = np.array(FP["29559536"]["ring"]); top = r[r[:, 0] > r[:, 0].max() - 0.00008]; return float(top[:, 0].mean()), float(top[:, 1].mean())


# observations: (label, kind, geometry, x_norm, y_norm or None, top_asl_m or None, note)
SHOTS = [
 dict(id="01", file="01_IMG_1196", t="2026-11-08T08:21:32-05:00", horizon_y=0.414, obs=[
   ("Custom House Tower tip", "point", pk("Custom House Tower"), 0.889, 0.061, 3.0 + 151.2, "pack (Wikipedia 496 ft)"),
   ("Marketplace Center glass gable tip", "point", (42.3597087, -71.0529806), 0.567, 0.395, 4.0 + 40.0,
    "200 State St OSM address node; height ~40 m ESTIMATED (OSM 7 m is wrong); position +-20 m"),
   ("Harbor Towers I roof", "point", pk("Harbor Towers I"), 0.98, 0.325, 1.3 + 121.9, "pack (Wikipedia 400 ft)")]),
 dict(id="02", file="02_IMG_1197", t="2026-11-08T08:22:21-05:00", horizon_y=None, obs=[
   ("One Federal St roof", "point", (42.3568, -71.0567), 0.82, 0.19, 4.0 + 160.0, "seed coords; pack footprint centre 42.356165,-71.057016"),
   ("1891 Stock Exchange balustrade (53 State)", "point", stock_facade(), 0.50, 0.59, 5.0 + 50.0, "north-edge midpoint of the Exchange Place footprint; ~50 m"),
   ("Exchange Place left edge", "left", "29559536", 0.10, None, None, "silhouette vertex of OSM way 29559536"),
   ("Exchange Place right edge", "right", "29559536", 0.77, None, None, "silhouette vertex of OSM way 29559536")]),
 dict(id="03", file="03_IMG_1198", t="2026-11-08T08:22:54-05:00", horizon_y=None, obs=[
   ("Ames Building roof cornice (1 Court St)", "point", (42.35865, -71.05795), 0.474, 0.432, 6.0 + 60.0,
    "NOT in pack: hand-entered (seed coords; Wikipedia 196 ft); OSM footprint centre is 42.359031,-71.058072"),
   ("Old State House east gable", "point", osh_east(), 0.204, 0.748, 5.0 + 20.0, "east end of OSM way 29608515; 20 m"),
   ("Boston Massacre circle", "point", pk("Boston Massacre Site"), 0.463, 0.899, 5.0, "pack node; ground level"),
   ("28 State St SE edge", "corner_se", "29614103", 0.54, None, None, "SE vertex of OSM way 29614103"),
   ("One Boston Place left edge", "left", "816922979", 0.19, None, None, "silhouette vertex of OSM way 816922979")]),
 dict(id="04", file="04_IMG_1199", t="2026-11-08T08:23:36-05:00", horizon_y=None, obs=[
   ("Hub on Causeway / Verizon roof", "point", (42.36597, -71.06117), 0.31, 0.40, 4.0 + 155.0, "seed coords, 155 m"),
   ("Bunker Hill Monument tip", "point", pk("Bunker Hill Monument"), 0.603, 0.473, 24.4 + 67.4, "pack (Wikipedia 221 ft)"),
   ("Holocaust Memorial glass tower", "point", (42.361316, -71.057329), 0.455, 0.635, 4.0 + 16.5, "OSM way 148772838; 16.5 m"),
   ("One Congress roof edge", "skip", None, 0.17, 0.30, None, "NOT used: which roof edge is ambiguous")]),
]


def ring_en(fid):
    return np.array([LOC.en(a, o) for a, o in FP[fid]["ring"]])


def pred_bearing(o, P):
    kind, geo = o[1], o[2]
    if kind == "point":
        return R.bearing(P, LOC.en(*geo))
    rg = ring_en(geo)
    if kind == "corner_se":
        return R.bearing(P, rg[np.argmax(rg[:, 0] - rg[:, 1])])
    b = np.array([R.bearing(P, q) for q in rg]); ref = b[0]; rel = np.array([R.wrap(x - ref) for x in b])
    return ref + (rel.min() if kind == "left" else rel.max())


def phi_of(o):
    return math.atan((o[3] * W_IMG - CX) / F)


def fit_heading(P, obs):
    return math.atan2(*np.sum([[math.sin(pred_bearing(o, P) - phi_of(o)), math.cos(pred_bearing(o, P) - phi_of(o))] for o in obs], 0))


def resid(P, th, obs):
    return np.array([R.wrap(pred_bearing(o, P) - (th + phi_of(o))) for o in obs])


def solve_shot(obs):
    best = None
    for e in np.arange(-700, 701, 20.0):         # grid over downtown (no prior on the building)
        for n in np.arange(-700, 701, 20.0):
            P = np.array([e, n])
            if any(o[1] == "point" and np.linalg.norm(LOC.en(*o[2]) - P) < 15 for o in obs):
                continue
            th = fit_heading(P, obs); c = float((resid(P, th, obs) ** 2).sum())
            if best is None or c < best[0]:
                best = (c, P, th)
    x = np.array([*best[1], best[2]])
    for _ in range(40):                          # Gauss-Newton, numerical Jacobian
        r0 = resid(x[:2], x[2], obs); J = np.zeros((len(obs), 3))
        for k, dk in enumerate((0.5, 0.5, 1e-4)):
            xx = x.copy(); xx[k] += dk; J[:, k] = (resid(xx[:2], xx[2], obs) - r0) / dk
        dx = np.linalg.lstsq(J, -r0, rcond=None)[0]; x += dx
        if abs(dx[0]) + abs(dx[1]) < 1e-3:
            break
    r = resid(x[:2], x[2], obs)
    return x[:2], R.wrap(x[2]), r


# ---------------- glazing gate ----------------
B155 = next(b for b in json.loads((C / "pack/buildings.json").read_text())["buildings"]
            if abs(b["h"] - 155) < 0.1 and any(abs(p[0] - 42.3592) < 0.0005 and abs(p[1] + 71.0564) < 0.0006 for p in b["ring"]))
OUT = np.array([LOC.en(a, o) for a, o in B155["ring"]])
AREA = 0.5 * sum(OUT[i, 0] * OUT[i + 1, 1] - OUT[i + 1, 0] * OUT[i, 1] for i in range(len(OUT) - 1))


def segments():
    segs = []
    for i in range(len(OUT) - 1):
        a, b = OUT[i], OUT[i + 1]; d = b - a; L = float(np.linalg.norm(d))
        if L < 0.5:
            continue
        nrm = np.array([d[1], -d[0]]) / L if AREA > 0 else np.array([-d[1], d[0]]) / L    # outward
        nb = math.degrees(math.atan2(nrm[0], nrm[1])) % 360
        face = "NESW"[int(((nb + 45) % 360) // 90)]
        segs.append(dict(i=i, a=a, b=b, L=L, normal_deg=nb, face=face))
    return segs


SEGS = segments()


def gate(P, th):
    hd = math.degrees(th) % 360; cands = []
    for s in SEGS:
        d = s["b"] - s["a"]; t = float(np.clip((P - s["a"]) @ d / (d @ d), 0, 1)); Q = s["a"] + t * d
        off = abs((hd - s["normal_deg"] + 180) % 360 - 180)
        cands.append((float(np.linalg.norm(P - Q)), off, Q, s))
    ok = [c for c in cands if c[1] <= 35]
    pick = min(ok, key=lambda c: c[0]) if ok else min(cands, key=lambda c: c[0])
    return pick, bool(ok)


def face_mid(face):
    s = max((s for s in SEGS if s["face"] == face), key=lambda s: s["L"]); return (s["a"] + s["b"]) / 2


def dipdeg(h):
    return 0.0293 * math.sqrt(max(h, 0))


def heights(shot, P):
    out = []; yh = shot.get("horizon_y")
    for o in shot["obs"]:
        if o[1] != "point" or o[5] is None or o[4] is None:
            continue
        q = LOC.en(*o[2]); d = float(np.linalg.norm(q - P)); py = o[4] * H_IMG
        a_axis = math.atan((CY - py) / F)
        if yh is not None:                        # elevation above the sea horizon, minus dip; iterate h twice
            h = 55.0
            for _ in range(2):
                el = a_axis - math.atan((CY - yh * H_IMG) / F) - math.radians(dipdeg(h + GROUND_CAM))
                h = o[5] - d * math.tan(el) - GROUND_CAM
            src = "(a) vs sea horizon + dip" if o[5] == max(x[5] for x in shot["obs"] if x[5]) else "(b) vs sea horizon + dip"
        else:
            el = a_axis; h = o[5] - d * math.tan(el) - GROUND_CAM; src = "(b) level camera assumed (no horizon)"
        out.append({"shot": shot["id"], "landmark": o[0], "dist_m": round(d, 1), "elev_deg": round(math.degrees(el), 2),
                    "h_above_street_m": round(h, 1), "source": src})
    return out


def shot_h_pitch(shot, P):
    """(c) per-shot camera height AND pitch from >= 2 known-height landmarks (least squares over a 0.1 m grid in h, pitch = mean
    residual). Used for shots without a sea horizon instead of assuming a level camera."""
    L = []
    for o in shot["obs"]:
        if o[1] == "point" and o[5] is not None and o[4] is not None:
            d = float(np.linalg.norm(LOC.en(*o[2]) - P)); L.append((o[5], d, math.atan((CY - o[4] * H_IMG) / F)))
    if len(L) < 2:
        return None
    best = None
    for h in np.arange(0, 150, 0.1):
        r = np.array([math.atan2(T - h - GROUND_CAM, d) - a for T, d, a in L]); p = r.mean(); c = float(((r - p) ** 2).sum())
        if best is None or c < best[0]:
            best = (c, h, p)
    return {"h_above_street_m": round(float(best[1]), 1), "pitch_deg": round(math.degrees(best[2]), 2),
            "rms_deg": round(math.degrees(math.sqrt(best[0] / len(L))), 2), "n": len(L)}


def main():
    truth = json.loads((C / "results/course_truth.json").read_text())
    res = []; allh = []
    for s in SHOTS:
        obs = [o for o in s["obs"] if o[1] != "skip"]
        P, th, r = solve_shot(obs)
        (dist, off, Q, seg), ok = gate(P, th)
        th2 = fit_heading(Q, obs); r2 = resid(Q, th2, obs)
        hs = heights(s, Q); allh += hs
        lat, lon = LOC.ll(*P); lat2, lon2 = LOC.ll(*Q)
        res.append({"shot": s["id"], "file": s["file"], "time": s["t"], "n_obs": len(obs),
                    "pre_gate": {"lat": round(lat, 6), "lon": round(lon, 6), "heading_deg": round(math.degrees(th) % 360, 1),
                                 "rms_deg": round(math.degrees(float(np.sqrt((r ** 2).mean()))), 2)},
                    "gate": {"moved_m": round(dist, 1), "face": seg["face"], "segment": seg["i"], "face_normal_deg": round(seg["normal_deg"], 1),
                             "heading_vs_normal_deg": round(off, 1), "heading_rule_ok": ok},
                    "post_gate": {"lat": round(lat2, 6), "lon": round(lon2, 6), "e": round(float(Q[0]), 1), "n": round(float(Q[1]), 1),
                                  "heading_deg": round(math.degrees(th2) % 360, 1), "rms_deg": round(math.degrees(float(np.sqrt((r2 ** 2).mean()))), 2),
                                  "residuals_deg": [round(math.degrees(x), 2) for x in r2]},
                    "obs": [{"label": o[0], "kind": o[1], "x": o[3], "y": o[4], "top_asl_m": o[5], "note": o[6]} for o in s["obs"]],
                    "heights": hs})
        if s["id"] == "03":                       # where does the Massacre-circle pixel land on the ground?
            o = next(o for o in s["obs"] if o[0].startswith("Boston Massacre"))
            el = math.atan((CY - o[4] * H_IMG) / F)
            res[-1]["massacre_check"] = {"note": "computed after the joint height is known; see below"}
    per_shot_h = []
    for x, s in zip(res, SHOTS):
        Q = np.array([x["post_gate"]["e"], x["post_gate"]["n"]])
        if s.get("horizon_y") is not None:
            a = next(h for h in x["heights"] if h["source"].startswith("(a)"))
            x["shot_h"] = {"h_above_street_m": a["h_above_street_m"], "source": "(a) " + a["landmark"] + " vs sea horizon + dip"}
        else:
            c = shot_h_pitch(s, Q); x["shot_h"] = dict(c, source=f"(c) joint pitch+h fit over {c['n']} known-height landmarks")
            if abs(c["pitch_deg"]) > 15 or c["rms_deg"] > 1.0:      # rule fixed before scoring: phone held near level
                x["shot_h"]["converged"] = False; x["shot_h"]["why"] = "|pitch| > 15 deg or rms > 1 deg: degenerate fit, excluded from the joint median"
                continue
        x["shot_h"]["converged"] = True
        per_shot_h.append(x["shot_h"]["h_above_street_m"])
    hj = float(np.median(per_shot_h)); floor = round((hj - 6) / 3.85) + 1
    hvals = [x["h_above_street_m"] for x in allh]
    # Massacre circle ground point with the joint height
    for r_ in res:
        if r_["shot"] == "03":
            Q = np.array([r_["post_gate"]["e"], r_["post_gate"]["n"]]); s = SHOTS[2]; o = next(o for o in s["obs"] if o[0].startswith("Boston Massacre"))
            el = math.atan((CY - o[4] * H_IMG) / F); d = (hj + GROUND_CAM - 5.0) / math.tan(-el)
            b = math.radians(r_["post_gate"]["heading_deg"]) + phi_of(o); G = Q + d * np.array([math.sin(b), math.cos(b)])
            node = LOC.en(*o[2]); dv = G - node
            r_["massacre_check"] = {"ground_point": [round(v, 6) for v in LOC.ll(*G)], "vs_pack_node_m": round(float(np.linalg.norm(dv)), 1),
                                    "north_offset_m": round(float(dv[1]), 1), "east_offset_m": round(float(dv[0]), 1),
                                    "note": "ray through the tapped circle pixel, level camera, joint h; positive north = circle is north of the node"}
    # chain
    legs = []
    for a, b in zip(res, res[1:]):
        pa = np.array([a["post_gate"]["e"], a["post_gate"]["n"]]); pb = np.array([b["post_gate"]["e"], b["post_gate"]["n"]])
        from datetime import datetime
        dt = (datetime.fromisoformat(b["time"]) - datetime.fromisoformat(a["time"])).total_seconds(); L = float(np.linalg.norm(pb - pa))
        legs.append({"from": a["shot"], "to": b["shot"], "dt_s": dt, "vector_en_m": [round(float(v), 1) for v in pb - pa], "straight_m": round(L, 1),
                     "corridor_m": round(1.5 * L, 1), "speed_m_s": round(1.5 * L / dt, 2)})
    pts = [(x["post_gate"]["e"], x["post_gate"]["n"]) for x in res]
    sa = 0.5 * sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4))
    direction = "clockwise" if sa < 0 else "counter-clockwise"
    faces = [x["gate"]["face"] for x in res]
    # score
    score = []
    for x, t in zip(res, truth["shots"]):
        Q = np.array([x["post_gate"]["e"], x["post_gate"]["n"]]); P0 = LOC.en(x["pre_gate"]["lat"], x["pre_gate"]["lon"]); M = face_mid(t["face"])
        he = (x["post_gate"]["heading_deg"] - t["heading_deg"] + 180) % 360 - 180
        score.append({"shot": x["shot"], "true_face": t["face"], "solved_face": x["gate"]["face"],
                      "pos_err_pre_gate_m": round(float(np.linalg.norm(P0 - M)), 1), "pos_err_m": round(float(np.linalg.norm(Q - M)), 1),
                      "heading_err_deg": round(he, 1)})
    hlo, hhi = truth["h_above_street_m"]
    herr = 0.0 if hlo <= hj <= hhi else round(min(abs(hj - hlo), abs(hj - hhi)), 1)
    out = {"shots": res, "heights_all": allh, "per_shot_h_m": per_shot_h, "median_of_all_b_estimates_m": round(float(np.median(hvals)), 1),
           "joint_h_m": round(hj, 1), "joint_h_rule": "median of the four per-shot heights: 01 (a) sea horizon; 02-04 (c) pitch+h fit", "floor_est": floor, "floor_rule": "round((h - 6) / 3.85) + 1",
           "legs": legs, "total_s": sum(l["dt_s"] for l in legs), "signed_area_m2": round(sa, 1), "direction": direction, "faces": faces,
           "score": {"per_shot": score, "h_err_m": herr, "h_err_vs_58_m": round(hj - 58, 1), "floor_truth": truth["floor"],
                     "floor_right": floor == truth["floor"], "direction_right": direction == truth["direction"],
                     "faces_right": faces == [t["face"] for t in truth["shots"]]},
           "f_px": F, "outline": {"osm_h": B155["h"], "signed_area": round(AREA, 1)},
           "metadata_used": "EXIF DateTimeOriginal + FocalLengthIn35mmFilm only; no GPS tags, no GPSImgDirection (none present)"}
    (C / "results/course.json").write_text(json.dumps(out, indent=1))
    for x in res:
        print(x["shot"], "pre", x["pre_gate"], "| gate", x["gate"], "| post", {k: x["post_gate"][k] for k in ("lat", "lon", "heading_deg", "rms_deg")})
    for h in allh:
        print("  h", h)
    for x in res:
        print("  shot h", x["shot"], x["shot_h"])
    print("joint h", round(hj, 1), "floor", floor, "| direction", direction, faces)
    for l in legs:
        print("  leg", l)
    print(json.dumps(out["score"], indent=1))
    for x in res:
        if "massacre_check" in x:
            print("massacre", x["massacre_check"])
    return out


if __name__ == "__main__":
    main()
