"""Zero-shot PANNs (CNN14) and AST (AudioSet) on 'Dog play pant' (Zenodo 18972388, CC BY 4.0) expert labels.

Usage: ~/forge/.venv/bin/python eval_dog.py  -> land/results.json + land/RESULTS.md
Segments: every expert-reviewed (SecondLayer) annotation in the 30 play-session WAVs. Each segment is cut as a window
centred on the call, length max(1 s, call length) capped at 4 s, resampled to each model's rate.
 1. Dog presence: score = max over AudioSet dog classes. Positives = dog calls; negatives = 'Human' noise segments.
    ROC AUC and accuracy at threshold 0.3.
 2. Call type, 4 groups that have AudioSet counterparts: Bark/yelp->{Bark, Yip, Bow-wow}, Whine->{Whimper (dog)},
    Growl->{Growling}, Pant->{Pant/Panting}. Top-1 among the 4 group scores; per-class recall and confusion.
 'Howl' never occurs in this dataset (no howl label), so howl cannot be validated here.
"""
import sys, json, glob, collections
from pathlib import Path
import numpy as np, soundfile as sf, librosa

sys.path.insert(0, str(Path.home() / "forge/night/perch"))
from audio_presence import PannsTagger, AstTagger  # noqa: E402

L = Path(__file__).resolve().parent; D = L / "dog03"
GROUPS = {"Bark/yelp": ["Bark", "Yip", "Bow-wow"], "Whine": ["Whimper (dog)"], "Growl": ["Growling"], "Pant": ["Pant", "Panting"]}
DOG = ["Dog", "Bark", "Yip", "Howl", "Bow-wow", "Growling", "Whimper (dog)"]


def segments():
    segs = []
    for ann in sorted(glob.glob(str(D / "04 Annotations/SecondLayer/*.Table*"))):
        stem = Path(ann).name.split(".Table")[0]
        wav = next(iter(glob.glob(str(D / f"03 Play session recordings/*/{stem}.wav"))), None)
        if not wav:
            continue
        for ln in open(ann).read().split("\n")[1:]:
            p = ln.split("\t")
            if len(p) < 4 or p[0] == "tmin":
                continue
            t0, tier, text, t1 = float(p[0]), p[1].strip(), p[2].strip(), float(p[3])
            segs.append({"wav": wav, "t0": t0, "t1": t1, "tier": tier, "label": text})
    return segs


def cut(wav, t0, t1, sr, cache={}):
    if wav not in cache:
        x, fs = sf.read(wav, dtype="float32", always_2d=True); cache.clear(); cache[wav] = (x.mean(1), fs)
    x, fs = cache[wav]; c = (t0 + t1) / 2; L_ = min(max(1.0, t1 - t0), 4.0)
    a = max(0, int((c - L_ / 2) * fs)); b = min(len(x), int((c + L_ / 2) * fs))
    y = librosa.resample(x[a:b], orig_sr=fs, target_sr=sr)
    n = int(L_ * sr); return np.pad(y, (0, max(0, n - len(y))))[:n]


def auc(pos, neg):
    s = np.concatenate([pos, neg]); r = s.argsort().argsort() + 1
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def run(tagger, segs):
    idx = {l: i for i, l in enumerate(tagger.labels)}
    miss = [l for l in DOG + sum(GROUPS.values(), []) if l not in idx]
    S = []
    for s in sorted(segs, key=lambda s: s["wav"]):
        y = cut(s["wav"], s["t0"], s["t1"], tagger.sr)
        S.append((s, tagger.scores(y[None])[0]))
    dogi = [idx[l] for l in DOG if l in idx]
    pos = np.array([sc[dogi].max() for s, sc in S if s["tier"] == "calls"])
    neg = np.array([sc[dogi].max() for s, sc in S if s["label"] == "Human"])
    per_lab = collections.defaultdict(list)
    for s, sc in S:
        if s["tier"] == "calls":
            per_lab[s["label"].strip()].append(float(sc[dogi].max()))
    conf = {g: collections.Counter() for g in GROUPS}
    for s, sc in S:
        if s["label"] in GROUPS:
            gs = {g: max(sc[idx[l]] for l in ls if l in idx) for g, ls in GROUPS.items()}
            conf[s["label"]][max(gs, key=gs.get)] += 1
    bi = [idx[l] for l in GROUPS["Bark/yelp"] if l in idx]
    bp = np.array([sc[bi].max() for s, sc in S if s["label"] == "Bark/yelp"]); bn = np.array([sc[bi].max() for s, sc in S if s["label"] != "Bark/yelp"])
    bark = {"n_bark": len(bp), "n_other": len(bn), "AUC_bark_vs_all_other": round(auc(bp, bn), 3)}
    for th in (0.3, 0.5):
        tp = int((bp >= th).sum()); fp = int((bn >= th).sum())
        bark[f"at_{th}"] = {"precision": round(tp / max(1, tp + fp), 3), "recall": round(tp / max(1, len(bp)), 3), "TP": tp, "FP": fp}
    rec = {g: round(c[g] / max(1, sum(c.values())), 3) for g, c in conf.items()}
    n = sum(sum(c.values()) for c in conf.values()); acc = sum(conf[g][g] for g in GROUPS) / max(1, n)
    return {"model": tagger.name, "missing_labels": miss, "bark_detector": bark,
            "presence": {"n_dog_calls": len(pos), "n_human": len(neg), "AUC_dog_vs_human": round(auc(pos, neg), 3),
                         "recall_at_0.3": round(float((pos >= 0.3).mean()), 3), "false_alarm_on_human_at_0.3": round(float((neg >= 0.3).mean()), 3),
                         "median_dog_score_by_label": {k: round(float(np.median(v)), 3) for k, v in sorted(per_lab.items())}},
            "call_type": {"n": n, "top1_accuracy_4way": round(acc, 3), "chance_majority": round(max(sum(c.values()) for c in conf.values()) / max(1, n), 3),
                          "recall": rec, "confusion": {g: dict(c) for g, c in conf.items()}}}


if __name__ == "__main__":
    segs = segments(); print(len(segs), "segments", collections.Counter(s["label"] for s in segs).most_common(12))
    res = {"dataset": "Dog play pant (Zenodo 18972388, CC BY 4.0): 30 annotated play sessions, 17 dogs, expert-reviewed SecondLayer labels",
           "n_segments": len(segs), "labels": dict(collections.Counter(s["label"] for s in segs)),
           "howl": "no 'Howl' label in this dataset; howl detection is not validated", "models": []}
    for T in (PannsTagger, AstTagger):
        r = run(T("cuda"), segs); res["models"].append(r); print(json.dumps(r, indent=1))
    (L / "results.json").write_text(json.dumps(res, indent=1))
