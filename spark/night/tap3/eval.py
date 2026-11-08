"""Evaluate Tap Three on negatives (and positives when Franco's recordings land).

Negatives on disk:
  ESC-50 door_wood_knock + footsteps (40 x 5 s clips each): per clip, and concatenated as one stream
  footstep_8env.mat geophone (576 recordings). The .mat does not carry a sample rate; the step
  period is ~3500 samples, so we evaluate at assumed fs 5000 / 6500 / 8000 Hz and report all three.
Positives/negatives recorded by the team: night/data/tap3/{pos,neg}/*.wav (or *pos*/*neg* in name).

Writes night/tap3/eval_results.json; RESULTS.md is written from it.
"""
from __future__ import annotations
import csv, json, sys, time
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from detect import detect  # noqa

ESC = Path("/mnt/hackssd/GB10_ARSENAL/datasets/esc-50")
MAT = Path.home() / "forge/datasets/vibration/footstep_8env.mat"
TEAM = HERE.parent / "data/tap3"


def counts(r):
    k = [e["kind"] for e in r["events"]]
    return k.count("pattern"), k.count("confirmed")


def esc(cat):
    rows = [r for r in csv.DictReader(open(ESC / "meta/esc50.csv")) if r["category"] == cat]
    clips = []
    for r in rows:
        x, fs = sf.read(ESC / "audio" / r["filename"]); clips.append((r["filename"], x, fs))
    per = [(f, *counts(detect(x, fs))) for f, x, fs in clips]
    fs = clips[0][2]
    stream = np.concatenate([x for _, x, _ in clips])
    sp, sc = counts(detect(stream, fs))
    hours = len(stream) / fs / 3600
    return {"clips": len(clips), "hours": round(hours, 4),
            "clips_with_pattern": sum(1 for p in per if p[1]), "clips_with_confirmed": sum(1 for p in per if p[2]),
            "stream_patterns": sp, "stream_confirmed": sc,
            "pattern_fa_per_h": round(sp / hours, 2), "confirmed_fa_per_h": round(sc / hours, 2),
            "flagged_clips": [p[0] for p in per if p[1]]}


def geophone(fs_assumed):
    import scipy.io as sio
    m = sio.loadmat(MAT)
    keys = [k for k in m if not k.startswith("__")]
    tot_s = 0; P = C = 0; flagged = []
    for k in keys:
        x = np.asarray(m[k][0, 0]["vibration"], float).ravel()
        r = detect(x, fs_assumed); p, c = counts(r)
        P += p; C += c; tot_s += len(x) / fs_assumed
        if p: flagged.append(k)
    h = tot_s / 3600
    return {"fs_assumed": fs_assumed, "recordings": len(keys), "hours": round(h, 3),
            "patterns": P, "confirmed": C, "pattern_fa_per_h": round(P / h, 2),
            "confirmed_fa_per_h": round(C / h, 2), "recordings_with_pattern": len(flagged),
            "flagged_sample": flagged[:10]}


def team():
    files = sorted(TEAM.rglob("*.wav"))
    if not files:
        return None
    res = {"pos": [], "neg": []}
    for f in files:
        lab = "pos" if ("pos" in f.parent.name.lower() or "pos" in f.stem.lower()) else \
              "neg" if ("neg" in f.parent.name.lower() or "neg" in f.stem.lower()) else None
        if lab is None: continue
        x, fs = sf.read(f, always_2d=False)
        if x.ndim > 1: x = x.mean(1)
        p, c = counts(detect(x, fs)); res[lab].append((f.name, p, c, len(x) / fs))
    out = {}
    if res["pos"]:
        n = len(res["pos"])
        out["pos_n"] = n
        out["hit_rate_pattern"] = round(sum(1 for r in res["pos"] if r[1]) / n, 3)
        out["hit_rate_confirmed"] = round(sum(1 for r in res["pos"] if r[2]) / n, 3)
        out["missed"] = [r[0] for r in res["pos"] if not r[1]]
    if res["neg"]:
        h = sum(r[3] for r in res["neg"]) / 3600
        out["neg_n"] = len(res["neg"]); out["neg_hours"] = round(h, 4)
        out["neg_pattern_fa_per_h"] = round(sum(r[1] for r in res["neg"]) / h, 2)
        out["neg_confirmed_fa_per_h"] = round(sum(r[2] for r in res["neg"]) / h, 2)
        out["neg_flagged"] = [r[0] for r in res["neg"] if r[1]]
    return out


def synthetic_sensitivity():
    """SYNTHETIC: decaying-sinusoid taps (2 patterns, gap 0.7-1.3 s, +-5 % jitter) added to real
    ESC-50 footsteps/knock/rain streams at several tap-to-background peak ratios. Not a field hit rate."""
    from detect import synth_taps
    rng = np.random.default_rng(1)
    out = {}
    for cat in ("footsteps", "door_wood_knock", "rain"):
        rows = [r for r in csv.DictReader(open(ESC / "meta/esc50.csv")) if r["category"] == cat]
        bg = np.concatenate([sf.read(ESC / "audio" / r["filename"])[0] for r in rows]); fs = 44100
        bg = bg / (np.max(np.abs(bg)) + 1e-9)
        for ratio in (8.0, 4.0, 2.0, 1.0):
            hits_p = hits_c = 0; trials = 30
            for k in range(trials):
                gap = rng.uniform(0.7, 1.3); t0 = rng.uniform(1, 3)
                tt = [t0 + i * gap * (1 + rng.uniform(-.05, .05)) for i in range(3)]
                t1 = tt[-1] + rng.uniform(2.5, 4.0)
                tt += [t1 + i * gap * (1 + rng.uniform(-.05, .05)) for i in range(3)]
                dur = tt[-1] + 3
                taps = synth_taps(fs=fs, dur=dur, tap_times=tt, noise=0.0, seed=k)
                taps = taps / np.max(np.abs(taps))
                i0 = rng.integers(0, len(bg) - int(dur * fs))
                x = bg[i0:i0 + int(dur * fs)] + ratio * taps[:int(dur * fs)]
                p_, c_ = counts(detect(x, fs)); hits_p += p_ > 0; hits_c += c_ > 0
            out[f"{cat}@{ratio}"] = {"trials": trials, "pattern_rate": hits_p / trials, "confirmed_rate": hits_c / trials}
    return out


def main():
    t = time.time()
    out = {"run_at": time.strftime("%Y-%m-%d %H:%M"),
           "esc50_door_wood_knock": esc("door_wood_knock"),
           "esc50_footsteps": esc("footsteps"),
           "geophone": [geophone(f) for f in (5000, 6500, 8000)],
           "team_recordings": team(),
           "SYNTHETIC_sensitivity": synthetic_sensitivity()}
    out["runtime_s"] = round(time.time() - t, 1)
    (HERE / "eval_results.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
