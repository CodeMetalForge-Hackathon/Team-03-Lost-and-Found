"""Perch-and-listen contrast on one DroneAudioSet configuration.

Configuration: speaker-loudness 60 dB (and 90 dB for contrast), room1, drone1, speaker 1 m,
mic-dist 50 cm, mic3_8array-up (8 channels averaged to mono). On Hugging Face the source level
is named in dB; the repo README's "Volume 80pc" sample setting is not a folder on the Hub.

  perched   = source-only recording   (rotors off: the drone has landed and cut its motors)
  in flight = drone-with-source, throttle-low and throttle-high (DroneAudioSet's drone is on a
              frame, not free-flying; rotor noise is real)
Same file, same time window, so the human sound is identical; only the rotor noise differs.

Windows: the ground-truth source audio is scanned with PANNs; the 3 windows (5 s) with the highest
human-vocal (HV) score are used. Then AST and PANNs tag every condition.

  python tag.py            -> prints top tags, writes clips/*.wav and results.json for demo.html
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import soundfile as sf
import librosa

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from audio_presence import PannsTagger, AstTagger, presence, top_k  # noqa: E402

DAS = Path.home() / "forge/datasets/das_wav"
LOC = HERE.parent / "data/das/wav"
GT = DAS / "ground-truth-audio"
WIN_S = 5.0


def cond_paths(file, db):
    base_dws = DAS if db == 60 else LOC
    p = {
        "perched (rotors off)": LOC / f"source-only-recordings/speaker-loudness-{db}db/room1/speaker-dist-1m/mic-dist-50cm/mic3_8array-up-{file}.wav",
        "in flight, throttle low": base_dws / f"drone-with-source-recordings/speaker-loudness-{db}db/room1/drone1/speaker-dist-1m/mic-dist-50cm/throttle-low/mic3_8array-up-{file}.wav",
        "in flight, throttle high": base_dws / f"drone-with-source-recordings/speaker-loudness-{db}db/room1/drone1/speaker-dist-1m/mic-dist-50cm/throttle-high/mic3_8array-up-{file}.wav",
    }
    return {k: v for k, v in p.items() if v.exists()}


def read_window(path, t0, sr):
    info = sf.info(str(path))
    a = int(t0 * info.samplerate); b = a + int(WIN_S * info.samplerate)
    x, fs = sf.read(str(path), start=a, stop=b, always_2d=True, dtype="float32")
    x = x.mean(axis=1)
    return librosa.resample(x, orig_sr=fs, target_sr=sr) if fs != sr else x


def main():
    panns = PannsTagger("cuda"); ast = AstTagger("cuda")
    clips = HERE / "clips"; clips.mkdir(exist_ok=True)
    # 1. choose windows from ground truth by PANNs HV score
    cands = []
    for f in ("File1", "File4"):
        g, fs = sf.read(str(GT / f"{f}.wav"), dtype="float32")
        g32 = librosa.resample(g, orig_sr=fs, target_sr=32000)
        starts = np.arange(0, len(g) / fs - WIN_S, 2.5)
        batch = np.stack([g32[int(s * 32000):int(s * 32000) + int(WIN_S * 32000)] for s in starts])
        sc = np.concatenate([panns.scores(batch[i:i + 16]) for i in range(0, len(batch), 16)])
        hv, _ = presence(sc, panns.labels, panns.map)
        for s, h, row in zip(starts, hv, sc):
            cands.append((float(h), f, float(s), top_k(row, panns.labels, 3)))
    cands.sort(reverse=True)
    chosen, used = [], set()
    for h, f, s, tk in cands:
        if any(f == uf and abs(s - us) < WIN_S for uf, us in used):
            continue
        chosen.append((f, s, h, tk)); used.add((f, s))
        if len(chosen) == 3:
            break
    results = {"config": "room1 / drone1 / speaker 1 m / mic-dist 50 cm / mic3_8array-up (8 ch mean)",
               "window_s": WIN_S, "clips": []}
    for f, s, h, tk in chosen:
        for db in (60, 90):
            paths = cond_paths(f, db)
            if not paths:
                continue
            entry = {"file": f, "t0": s, "db": db, "gt_panns_hv": round(h, 3), "gt_top": tk, "conditions": []}
            # ground truth clip too, for reference
            g = read_window(GT / f"{f}.wav", s, 16000)
            gname = f"{f}_{int(s)}s_groundtruth.wav"; sf.write(clips / gname, g / (np.abs(g).max() + 1e-9) * 0.9, 16000)
            entry["groundtruth_clip"] = gname
            for cname, p in paths.items():
                x16 = read_window(p, s, 16000); x32 = read_window(p, s, 32000)
                ps = panns.scores(x32[None])[0]; asr = ast.scores(x16[None])[0]
                p_hv, p_hnv = presence(ps[None], panns.labels, panns.map)
                a_hv, a_hnv = presence(asr[None], ast.labels, ast.map)
                slug = cname.split(" ")[0] + ("_" + cname.split()[-1] if "throttle" in cname else "")
                name = f"{f}_{int(s)}s_{db}db_{slug}.wav"
                # normalise for listening only; tags were computed on the raw level
                sf.write(clips / name, x16 / (np.abs(x16).max() + 1e-9) * 0.9, 16000)
                rms = float(np.sqrt(np.mean(x16 ** 2)))
                c = {"condition": cname, "clip": name, "rms_dbfs": round(20 * np.log10(rms + 1e-12), 1),
                     "panns": {"top": top_k(ps, panns.labels, 5), "p_hv": round(float(p_hv[0]), 3), "p_hnv": round(float(p_hnv[0]), 3)},
                     "ast": {"top": top_k(asr, ast.labels, 5), "p_hv": round(float(a_hv[0]), 3), "p_hnv": round(float(a_hnv[0]), 3)}}
                entry["conditions"].append(c)
                print(f"{f} t0={s:5.1f}s {db}dB {cname:26s} PANNs HV {c['panns']['p_hv']:.3f} top {c['panns']['top'][:3]} | "
                      f"AST HV {c['ast']['p_hv']:.3f} top {c['ast']['top'][:3]}")
            results["clips"].append(entry)
    (HERE / "results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
