"""Human-sound presence: AudioSet tagger -> P(HV), P(HNV). Optional enhancement pre-pass.

Honest limit: in-flight drone audio is weak. Use this at a ground node, a perch or a throttle-down window.
"""
from __future__ import annotations
import argparse, json, os, pathlib, subprocess, tempfile
import numpy as np
from audioset_map import build_map

PANNS_SR, AST_SR = 32000, 16000
DFN_PY = os.path.expanduser("~/dfn/bin/python")
DFN_WORKER = str(pathlib.Path(__file__).with_name("dfn_worker.py"))
PANNS_CKPT = os.path.expanduser("~/panns_data/Cnn14_mAP=0.431.pth")

class PannsTagger:
    name, sr = "panns-cnn14", PANNS_SR
    def __init__(self, device: str = "cuda"):
        from panns_inference import AudioTagging, labels
        self.at = AudioTagging(checkpoint_path=PANNS_CKPT, device=device)
        self.labels = list(labels)
        self.map = build_map(self.labels)
    def scores(self, batch: np.ndarray) -> np.ndarray:
        clip, _ = self.at.inference(batch)
        return clip

class AstTagger:
    name, sr = "ast-audioset", AST_SR
    def __init__(self, device: str = "cuda", path: str = "~/models/ast-audioset"):
        from transformers import ASTFeatureExtractor, ASTForAudioClassification
        import torch
        p = os.path.expanduser(path)
        self.torch, self.device = torch, device
        self.fe = ASTFeatureExtractor.from_pretrained(p)
        self.m = ASTForAudioClassification.from_pretrained(p).to(device).eval()
        self.labels = [self.m.config.id2label[i] for i in range(self.m.config.num_labels)]
        self.map = build_map(self.labels)
    def scores(self, batch: np.ndarray) -> np.ndarray:
        x = self.fe(list(batch), sampling_rate=self.sr, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            return self.torch.sigmoid(self.m(**x).logits).cpu().numpy()

def get_tagger(name: str = "panns", device: str = "cuda"):
    return PannsTagger(device) if name == "panns" else AstTagger(device)

def presence(scores: np.ndarray, labels: list[str], mp: dict[str, str]) -> tuple[np.ndarray, np.ndarray]:
    """P(class) = strongest label in that class."""
    hv = [i for i, l in enumerate(labels) if mp[l] == "HV"]
    hnv = [i for i, l in enumerate(labels) if mp[l] == "HNV"]
    return scores[:, hv].max(axis=1), scores[:, hnv].max(axis=1)

def top_k(scores: np.ndarray, labels: list[str], k: int = 5) -> list[tuple[str, float]]:
    idx = np.argsort(-scores)[:k]
    return [(labels[i], round(float(scores[i]), 3)) for i in idx]

def load_mono(path: str, sr: int) -> np.ndarray:
    import librosa, soundfile as sf
    x, fs = sf.read(path, always_2d=True, dtype="float32")
    x = x.mean(axis=1)
    return librosa.resample(x, orig_sr=fs, target_sr=sr) if fs != sr else x

def dfn_available() -> bool:
    return os.path.exists(DFN_PY)

def enhance_dfn(paths: list[str], outdir: str) -> list[str]:
    """DeepFilterNet3 in its own py3.11 venv. The deepFilter CLI dies in a DataLoader worker on this box, so use the API."""
    subprocess.run([DFN_PY, "-I", DFN_WORKER, outdir, *paths], check=True, capture_output=True, timeout=900)
    return [str(pathlib.Path(outdir) / pathlib.Path(p).name) for p in paths]

def enhance_nr(x: np.ndarray, sr: int) -> np.ndarray:
    import noisereduce
    return noisereduce.reduce_noise(y=x, sr=sr, stationary=False)

def to_detection(p_hv: float, p_hnv: float, sensor_id: str, lat, lon, model_id: str, thresh: float = 0.3, ce_m: float = 25.0) -> dict | None:
    """Thresholds need calibrating per site: see experiments/snr_sweep/findings.md."""
    if max(p_hv, p_hnv) < thresh:
        return None
    label, score = ("HV", p_hv) if p_hv >= p_hnv else ("HNV", p_hnv)
    return {"sensor_id": sensor_id, "modality": "acoustic", "lat": lat, "lon": lon, "ce_m": ce_m, "label": label, "score": float(score), "model_id": model_id}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav"); ap.add_argument("--tagger", default="panns", choices=["panns", "ast"])
    ap.add_argument("--device", default="cuda"); ap.add_argument("--sensor-id", default="gn2-mic")
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float); ap.add_argument("--post")
    a = ap.parse_args()
    t = get_tagger(a.tagger, a.device)
    x = load_mono(a.wav, t.sr)
    if t.name.startswith("ast"):
        x = x[: 10 * t.sr]
    s = t.scores(x[None, :])
    hv, hnv = presence(s, t.labels, t.map)
    d = to_detection(float(hv[0]), float(hnv[0]), a.sensor_id, a.lat, a.lon, t.name)
    print(json.dumps({"tagger": t.name, "top5": top_k(s[0], t.labels), "p_hv": float(hv[0]), "p_hnv": float(hnv[0]), "detection": d}, indent=1))
    if d and a.post:
        import requests
        requests.post(f"{a.post}/detections", json=d, timeout=5).raise_for_status()

if __name__ == "__main__":
    main()
