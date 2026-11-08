"""Linear probe on frozen AST embeddings: HV / HNV / NH from drone-with-source audio.

Labels: TEACHER labels. PANNs CNN14 tags the clean ground-truth source audio (File1-6) in the same
2 s window: HV if P(HV) >= 0.5; HNV if P(HNV) >= 0.4 and P(HV) < 0.2; NH if both < 0.1; otherwise
dropped as ambiguous. So the probe learns "what PANNs would say about the clean source", heard
through rotor noise. Not human annotation.
Data: 60 dB source, mic3_8array-up (8 ch mean), mic-dist 50 cm, throttle low and high.
Split by room and drone: TRAIN room1/drone1 1m + room1/drone2 1m + room2/drone1 3m;
TEST room3/drone2 3m (a room never seen in training).
Baseline: zero-shot AST (AudioSet head -> HV/HNV/NH by strongest class score) on the same test windows.

  python probe.py  -> RESULTS.md section numbers in probe_results.json
"""
from __future__ import annotations
import json, re, sys, time
from pathlib import Path
import numpy as np, soundfile as sf, librosa

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE.parent / "data/das"
IDX = Path.home() / "forge/tmp/das_index.json"
GT = Path.home() / "forge/datasets/das_wav/ground-truth-audio"
WIN, HOP = 2.0, 1.0
CONDS = {  # (room, drone, speaker dist) -> split
    ("room1", "drone1", "1m"): "train", ("room1", "drone2", "1m"): "train",
    ("room2", "drone1", "3m"): "train", ("room3", "drone2", "3m"): "test"}
PAT = re.compile(r"drone-with-source-recordings/speaker-loudness-60db/(room\d)/(drone\d)/speaker-dist-(\w+)/mic-dist-50cm/throttle-(low|high)/mic3_8array-up-(File\d)\.wav")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fetch():
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq
    idx = json.load(open(IDX))
    want = {}
    for row in idx:
        for p in row[2]:
            m = PAT.search(p)
            if m and (m.group(1), m.group(2), m.group(3)) in CONDS:
                want.setdefault(row[0], []).append(p)
    files = {}
    for shard, paths in sorted(want.items()):
        done = [OUT / "wav" / p for p in paths]
        if all(d.exists() for d in done):
            for p, d in zip(paths, done): files[p] = d
            continue
        log("download", shard)
        lp = hf_hub_download("ahlab-drone-project/DroneAudioSet", shard, repo_type="dataset", local_dir=str(OUT / "hf"))
        for b in pq.ParquetFile(lp).iter_batches(batch_size=1):
            fp = b.column("file_path")[0].as_py()
            if fp not in paths:
                continue
            a = b.column("audio")[0].as_py(); x = np.array(a["array"], dtype=np.float32)
            if x.ndim == 2 and x.shape[0] < x.shape[1]: x = x.T
            x = x.mean(axis=1) if x.ndim == 2 else x
            d = OUT / "wav" / fp; d.parent.mkdir(parents=True, exist_ok=True)
            sf.write(d, x, a["sampling_rate"]); files[fp] = d
        Path(lp).unlink()          # keep only the mono mic3 WAVs
    return files


def main():
    import torch
    from audio_presence import PannsTagger, AstTagger, presence
    files = fetch()
    log("files", len(files))
    panns = PannsTagger("cuda"); ast = AstTagger("cuda")
    # teacher labels per (File, window start)
    teacher = {}
    for f in sorted({PAT.search(p).group(5) for p in files}):
        g, fs = sf.read(str(GT / f"{f}.wav"), dtype="float32")
        g32 = librosa.resample(g, orig_sr=fs, target_sr=32000)
        starts = np.arange(0, len(g) / fs - WIN, HOP)
        batch = np.stack([g32[int(s * 32000):int(s * 32000) + int(WIN * 32000)] for s in starts])
        sc = np.concatenate([panns.scores(batch[i:i + 32]) for i in range(0, len(batch), 32)])
        hv, hnv = presence(sc, panns.labels, panns.map)
        for s, a, b in zip(starts, hv, hnv):
            lab = "HV" if a >= 0.5 else "HNV" if (b >= 0.4 and a < 0.2) else "NH" if (a < 0.1 and b < 0.1) else None
            if lab: teacher[(f, round(float(s), 1))] = lab
    log("teacher windows", len(teacher), {k: list(teacher.values()).count(k) for k in ("HV", "HNV", "NH")})
    # AST embeddings (mean of last hidden state) + zero-shot baseline
    X, y, split, thr, zs = [], [], [], [], []
    mp = ast.map
    hv_i = [i for i, l in enumerate(ast.labels) if mp[l] == "HV"]
    hnv_i = [i for i, l in enumerate(ast.labels) if mp[l] == "HNV"]
    for p, d in sorted(files.items()):
        room, drone, dist, throttle, f = PAT.search(p).groups()
        x, fs = sf.read(str(d), dtype="float32")
        if fs != 16000: x = librosa.resample(x, orig_sr=fs, target_sr=16000)
        keys = [(f, round(float(s), 1)) for s in np.arange(0, len(x) / 16000 - WIN, HOP)]
        keys = [k for k in keys if k in teacher]
        for i in range(0, len(keys), 32):
            kb = keys[i:i + 32]
            batch = [x[int(k[1] * 16000):int(k[1] * 16000) + int(WIN * 16000)] for k in kb]
            inp = ast.fe(batch, sampling_rate=16000, return_tensors="pt").to("cuda")
            with torch.no_grad():
                o = ast.m(**inp, output_hidden_states=True)
            emb = o.hidden_states[-1].mean(1).cpu().numpy()
            pr = torch.sigmoid(o.logits).cpu().numpy()
            for k, e, q in zip(kb, emb, pr):
                X.append(e); y.append(teacher[k]); split.append(CONDS[(room, drone, dist)]); thr.append(throttle)
                h, n_ = q[hv_i].max(), q[hnv_i].max()
                zs.append("HV" if h >= 0.3 and h >= n_ else "HNV" if n_ >= 0.3 else "NH")
        log(p.split("speaker-loudness-60db/")[1], len(keys))
    X = np.array(X); y = np.array(y); split = np.array(split); thr = np.array(thr); zs = np.array(zs)
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import f1_score, classification_report, confusion_matrix
    tr, te = split == "train", split == "test"
    sc = StandardScaler().fit(X[tr])
    clf = LogisticRegression(max_iter=3000, C=0.5, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
    labels = ["HV", "HNV", "NH"]
    res = {"teacher_counts": {k: int((y == k).sum()) for k in labels},
           "n_train": int(tr.sum()), "n_test": int(te.sum()),
           "train": "room1/drone1@1m + room1/drone2@1m + room2/drone1@3m", "test": "room3/drone2@3m (unseen room)",
           "by_throttle": {}}
    for t in ("low", "high", "all"):
        m = te & ((thr == t) if t != "all" else True)
        if m.sum() == 0: continue
        pred = clf.predict(sc.transform(X[m]))
        res["by_throttle"][t] = {
            "n": int(m.sum()),
            "test_counts": {k: int((y[m] == k).sum()) for k in labels},
            "probe_f1": dict(zip(labels, np.round(f1_score(y[m], pred, labels=labels, average=None, zero_division=0), 3).tolist())),
            "probe_macro_f1": round(float(f1_score(y[m], pred, labels=labels, average="macro", zero_division=0)), 3),
            "zeroshot_ast_f1": dict(zip(labels, np.round(f1_score(y[m], zs[m], labels=labels, average=None, zero_division=0), 3).tolist())),
            "zeroshot_macro_f1": round(float(f1_score(y[m], zs[m], labels=labels, average="macro", zero_division=0)), 3),
            "probe_confusion(rows=true HV,HNV,NH)": confusion_matrix(y[m], pred, labels=labels).tolist()}
    (HERE / "probe_results.json").write_text(json.dumps(res, indent=1))
    log(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
