"""Sonar dead reckoning for the dog stand-in (one forward Grove ultrasonic ranger, 1 Hz heartbeats).

Model. Between two range discontinuities the dog is assumed to keep one heading and to move only along it,
toward or away from ONE fixed surface. Then the surface point W is fixed and the dog sits at P(t) = W - d(t) * h.
A discontinuity (|Δd| > 25 cm in one 1 s step, or echo gained/lost) is a heading change of UNKNOWN angle.
Turns are taken in place, so the block k+1 wall is W_{k+1} = P_end(k) + d_start(k+1) * h_{k+1}.

Heading solutions (both saved, both labelled):
  sensor_only : turns assumed 90°, alternating left/right, unanchored frame. Nothing measured fixes the angle.
  room_prior  : run 10 only. The corner seen in Franco's video/photo: left wall → glass wall (front) → side wall →
                open floor = headings 180° / 0° / 270° / 90° (local frame, 0° = +x, CCW). NOT MEASURED.

Usage: reconstruct.py RUN_DIR OUT_DIR [--room-prior]
"""
from __future__ import annotations
import csv, json, math, sys
from pathlib import Path
import numpy as np

JUMP_CM = 25.0        # |Δd| per 1 s step that counts as a discontinuity (heading change)
FLAT_CM = 4.0         # |Δd| per step below which the range is "flat"
WEAK_CM = 8.0         # a lone up/down step smaller than this is folded into flat
ROOM_PRIOR = [180.0, 0.0, 270.0, 90.0]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def load(run_dir: Path):
    hb = list(csv.DictReader(open(run_dir / "heartbeats.csv")))
    al = list(csv.DictReader(open(run_dir / "alerts.csv")))
    t0 = int(hb[0]["t_ms"])
    rows = []
    for r in hb:
        d = r["dist_cm"].strip()
        dv = float(d) if d not in ("", "-1") else math.nan
        if not math.isnan(dv) and dv < 0:
            dv = math.nan
        rows.append(dict(t=(int(r["t_ms"]) - t0) / 1000.0, d=dv, state=r["state"], activity=_f(r["activity"]),
                         temp_c=_f(r["temp_c"]), humidity=_f(r["humidity"]), therm_c=_f(r["therm_c"]),
                         ts=r["ts"]))
    alerts = [dict(t=round((int(a["t_ms"]) - t0) / 1000.0, 2), kind=a["alert"]) for a in al]
    return rows, alerts, t0


def heading_blocks(rows):
    """Split sample indices at discontinuities / echo gain-loss. Returns list of (i0, i1) inclusive."""
    blocks, s = [], 0
    for i in range(1, len(rows)):
        a, b = rows[i - 1]["d"], rows[i]["d"]
        brk = (math.isnan(a) != math.isnan(b)) or (not math.isnan(a) and abs(b - a) > JUMP_CM)
        if brk:
            blocks.append((s, i - 1)); s = i
    blocks.append((s, len(rows) - 1))
    return blocks


def step_labels(d):
    lab = []
    for k in range(1, len(d)):
        dd = d[k] - d[k - 1]
        lab.append("D" if dd < -FLAT_CM else "U" if dd > FLAT_CM else "F")
    # fold weak lone steps into flat
    for k, l in enumerate(lab):
        if l != "F":
            lone = (k == 0 or lab[k - 1] != l) and (k == len(lab) - 1 or lab[k + 1] != l)
            if lone and abs(d[k + 1] - d[k]) < WEAK_CM:
                lab[k] = "F"
    return lab


def segment(rows):
    blocks = heading_blocks(rows)
    legs = []
    for hid, (i0, i1) in enumerate(blocks):
        d = [rows[i]["d"] for i in range(i0, i1 + 1)]
        if math.isnan(d[0]):                               # echo lost: open floor, split on debounced state
            st = [rows[i]["state"] for i in range(i0, i1 + 1)]
            cuts = [0] + [k for k in range(1, len(st)) if st[k] != st[k - 1] and
                          all(x == st[k] for x in st[k:k + 2])] + [len(st)]
            for a, b in zip(cuts[:-1], cuts[1:]):
                legs.append(dict(i0=i0 + a, i1=i0 + b - 1, kind="open", heading_id=hid))
            continue
        start = 0
        # transitional first sample right after a break (range still settling) belongs to the turn
        if hid > 0 and len(d) >= 4:
            nxt = d[1:4]
            if abs(d[0] - np.median(nxt)) > 10 and (max(nxt) - min(nxt)) < 6:
                start = 1
        if hid > 0:
            prev_end = blocks[hid - 1][1]
            legs.append(dict(i0=prev_end, i1=i0 + start, kind="turn", heading_id=hid))
        dd = d[start:]
        if len(dd) == 1:
            legs.append(dict(i0=i0 + start, i1=i0 + start, kind="park", heading_id=hid)); continue
        lab = step_labels(dd)
        k = 0
        while k < len(lab):
            m = k
            while m + 1 < len(lab) and lab[m + 1] == lab[k]:
                m += 1
            kind = {"D": "approach", "U": "retreat", "F": "park"}[lab[k]]
            legs.append(dict(i0=i0 + start + k, i1=i0 + start + m + 1, kind=kind, heading_id=hid))
            k = m + 1
    return blocks, legs


def describe(rows, alerts, legs):
    out = []
    T = [(rows[L["i0"]]["t"], rows[L["i1"]]["t"], L["kind"]) for L in legs]

    def owner(t):   # each alert belongs to exactly one leg; a turn owns (start, end + 0.5 s]
        for n, (a, b, k) in enumerate(T):
            if k == "turn" and a < t <= b + 0.5:
                return n
        for n, (a, b, k) in enumerate(T):
            if k != "turn" and a <= t < (b if n < len(T) - 1 else b + 1.0):
                return n
        return None
    for n, L in enumerate(legs):
        R = rows[L["i0"]:L["i1"] + 1]
        t0, t1 = R[0]["t"], R[-1]["t"]
        ds = [r["d"] for r in R if not math.isnan(r["d"])]
        ev = [a for a in alerts if owner(a["t"]) == n]
        spd = None
        if L["kind"] in ("approach", "retreat") and t1 > t0 and len(ds) >= 2:
            spd = round(abs(ds[-1] - ds[0]) / (t1 - t0), 1)
        still = sum(r["state"] == "STILL" for r in R) / len(R)
        note = ""
        if L["kind"] == "park" and still < 0.5:
            note = "range flat but gait active (MOVING) — pushing at / holding against the surface"
        if L["kind"] == "open":
            note = "no echo within the ranger's reach: open floor, not a sensor fault"
        if L["kind"] == "turn":
            note = "range discontinuity = heading change of unknown angle"
        out.append(dict(leg=n, start=t0, end=t1, kind=L["kind"], heading_id=L["heading_id"],
                        d_min=min(ds) if ds else None, d_max=max(ds) if ds else None, mean_speed_cm_s=spd,
                        still_frac=round(still, 2), mean_activity=round(float(np.nanmean([r["activity"] for r in R])), 1),
                        events=[f'{a["kind"]}@{a["t"]:.1f}s' for a in ev], note=note))
    return out


def dead_reckon(rows, blocks, headings_deg):
    """Return per-sample (x, y, hx, hy) in metres + wall points per heading block. Open-floor blocks hold position."""
    P = np.zeros(2); xs = [None] * len(rows); walls = []
    for hid, (i0, i1) in enumerate(blocks):
        a = math.radians(headings_deg[hid]); h = np.array([math.cos(a), math.sin(a)])
        d0 = rows[i0]["d"]
        if math.isnan(d0):
            for i in range(i0, i1 + 1):
                xs[i] = (P[0], P[1], h[0], h[1])
            walls.append(None); continue
        k0 = i0
        if hid > 0 and i1 - i0 >= 3:          # transitional sample right after a break = still turning: hold P
            nxt = [rows[j]["d"] for j in range(i0 + 1, i0 + 4)]
            if abs(d0 - np.median(nxt)) > 10 and (max(nxt) - min(nxt)) < 6:
                xs[i0] = (P[0], P[1], h[0], h[1]); k0 = i0 + 1
        W = P + (rows[k0]["d"] / 100.0) * h
        walls.append(dict(heading_id=hid, x=W[0], y=W[1], hx=h[0], hy=h[1],
                          d_min_cm=min(rows[i]["d"] for i in range(k0, i1 + 1))))
        for i in range(k0, i1 + 1):
            Pi = W - (rows[i]["d"] / 100.0) * h
            xs[i] = (Pi[0], Pi[1], h[0], h[1])
        P = np.array(xs[i1][:2])
    return xs, walls


def main():
    run_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    room = "--room-prior" in sys.argv
    out.mkdir(parents=True, exist_ok=True)
    rows, alerts, t0 = load(run_dir)
    blocks, legs = segment(rows)
    L = describe(rows, alerts, legs)
    nb = len(blocks)
    sensor_only = [0.0]
    for k in range(1, nb):
        sensor_only.append(sensor_only[-1] + (90.0 if k % 2 else -90.0))
    sols = {"sensor_only": dict(headings_deg=sensor_only, measured=False,
                                label="SENSOR-ONLY: turns assumed 90° alternating; unanchored frame; angles NOT measured")}
    if room:
        if nb != len(ROOM_PRIOR):
            print(f"WARNING: {nb} heading blocks but room prior has {len(ROOM_PRIOR)}; room prior skipped")
        else:
            sols["room_prior"] = dict(headings_deg=ROOM_PRIOR, measured=False,
                                      label="ROOM-PRIOR: headings from the corner in Franco's video/photo (left wall → glass wall → side wall → open floor). NOT MEASURED")
    for k, s in sols.items():
        xs, walls = dead_reckon(rows, blocks, s["headings_deg"])
        s["walls"] = walls; s["_xs"] = xs
    hid_of = {}
    for hid, (i0, i1) in enumerate(blocks):
        for i in range(i0, i1 + 1):
            hid_of[i] = hid
    leg_of = {}
    for n, Lg in enumerate(legs):
        for i in range(Lg["i0"], Lg["i1"] + 1):
            leg_of.setdefault(i, n) if Lg["kind"] == "turn" else leg_of.__setitem__(i, n)
    with open(out / "track.csv", "w", newline="") as f:
        w = csv.writer(f)
        hdr = ["t", "d_cm", "x_along_m", "heading_id", "leg", "state", "activity", "temp_c", "humidity", "therm_c"]
        for k in sols:
            hdr += [f"{k}_x", f"{k}_y", f"{k}_hdg"]
        w.writerow(hdr)
        for i, r in enumerate(rows):
            hid = hid_of[i]; i0, i1 = blocks[hid]
            dmin = min((rows[j]["d"] for j in range(i0, i1 + 1) if not math.isnan(rows[j]["d"])), default=math.nan)
            xa = "" if math.isnan(r["d"]) else round((dmin - r["d"]) / 100.0, 3)
            row = [r["t"], "" if math.isnan(r["d"]) else r["d"], xa, hid, leg_of.get(i, ""), r["state"],
                   r["activity"], r["temp_c"], r["humidity"], r["therm_c"]]
            for k, s in sols.items():
                x, y, hx, hy = s["_xs"][i]
                row += [round(x, 3), round(y, 3), s["headings_deg"][hid]]
            w.writerow(row)
    for s in sols.values():
        s.pop("_xs")
    meta = dict(run=run_dir.name, source=str(run_dir), t0_ms=t0, duration_s=rows[-1]["t"], n_heartbeats=len(rows),
                n_alerts=len(alerts), alerts=alerts,
                method="sonar dead reckoning: x_along = d_min(block) − d(t); speed = −dd/dt; discontinuity (|Δd|>25 cm/s or echo gain/loss) = heading change of unknown angle",
                heading_blocks=[dict(heading_id=k, start=rows[a]["t"], end=rows[b]["t"]) for k, (a, b) in enumerate(blocks)],
                solutions=sols, legs=L)
    (out / "legs.json").write_text(json.dumps(meta, indent=1))
    print(f"{run_dir.name}: {len(rows)} HB, {len(blocks)} heading blocks, {len(L)} legs")
    print(f"{'#':>2} {'start':>5} {'end':>5} {'kind':9} {'hdg':>3} {'dmin':>5} {'dmax':>5} {'v cm/s':>6}  events / note")
    for l in L:
        print(f"{l['leg']:>2} {l['start']:5.0f} {l['end']:5.0f} {l['kind']:9} {l['heading_id']:>3} "
              f"{l['d_min'] if l['d_min'] is not None else '–':>5} {l['d_max'] if l['d_max'] is not None else '–':>5} "
              f"{l['mean_speed_cm_s'] if l['mean_speed_cm_s'] else '':>6}  {' '.join(l['events'])} {l['note'][:50]}")


if __name__ == "__main__":
    main()
