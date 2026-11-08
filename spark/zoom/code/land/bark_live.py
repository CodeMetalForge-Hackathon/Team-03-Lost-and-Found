"""dog_bark events from audio -> night/inbox (low weight). PANNs CNN14 zero-shot, validated in land/RESULTS.md.

Usage:
  bark_live.py --wav FILE [--offset_s 0] [--dur_s 136] [--speed 4]   replay a recording (labelled REPLAY in every event)
  bark_live.py --mic [--dur_s 120]                                      live mic, if a capture device is attached
Positions: the dog stand-in's floor position at the same moment of the newest processed dog run
(night/data/dog/*/layers.json track), so the bark lands where the dog is. With a SYNTHETIC run the event says so.
Window 1 s, hop 0.5 s; bark score = max(Bark, Yip, Bow-wow); event when score >= 0.5 (land/RESULTS.md: P 0.61, R 0.75
on 48 expert-labelled barks vs 2588 other segments), 2 s refractory. kind=dog_bark, modality weight from config.json.
"""
import sys, json, time, argparse
from pathlib import Path
import numpy as np, soundfile as sf, librosa

NIGHT = Path.home() / "forge/night"
sys.path.insert(0, str(NIGHT / "perch")); sys.path.insert(0, str(NIGHT / "fusion"))
from audio_presence import PannsTagger  # noqa: E402
import inbox  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("--wav"); ap.add_argument("--mic", action="store_true")
ap.add_argument("--offset_s", type=float, default=0); ap.add_argument("--dur_s", type=float, default=136)
ap.add_argument("--speed", type=float, default=4.0); ap.add_argument("--thresh", type=float, default=0.5)
ap.add_argument("--dry", action="store_true", help="print events, do not write to the inbox"); a = ap.parse_args()
runs = sorted(NIGHT.glob("data/dog/*/layers.json"), key=lambda p: (json.loads(p.read_text()).get("synthetic", False), -p.stat().st_mtime))
L = json.loads(runs[0].read_text()); T = np.array(L["track"]); ts0 = L["t_start_ms"]; syn = L.get("synthetic", False)
def dog_at(t_s):
    i = int(np.clip(np.searchsorted(T[:, 0], ts0 + t_s * 1000), 0, len(T) - 1)); return float(T[i, 1]), float(T[i, 2])
tag = PannsTagger("cuda"); SR = tag.sr
bi = [tag.labels.index(l) for l in ("Bark", "Yip", "Bow-wow")]
if a.mic:
    import sounddevice as sd
    x = sd.rec(int(a.dur_s * SR), samplerate=SR, channels=1, dtype="float32"); src = "live mic"
    print("recording", a.dur_s, "s from the default mic…"); sd.wait(); x = x[:, 0]
else:
    y, fs = sf.read(a.wav, dtype="float32", always_2d=True, start=int(a.offset_s * sf.info(a.wav).samplerate),
                    frames=int(a.dur_s * sf.info(a.wav).samplerate))
    x = librosa.resample(y.mean(1), orig_sr=fs, target_sr=SR); src = f"REPLAY of {Path(a.wav).name} (Dog play pant, CC BY 4.0) from {a.offset_s:.0f} s"
win, hop = SR, SR // 2; t0 = time.time(); last = -9; n = 0
starts = list(range(0, max(1, len(x) - win), hop))
for k in range(0, len(starts), 32):
    batch = np.stack([x[s:s + win] for s in starts[k:k + 32]]); sc = tag.scores(batch)[:, bi].max(1)
    for s, p in zip(starts[k:k + 32], sc):
        t = s / SR
        if p >= a.thresh and t - last >= 2.0:
            last = t; xx, yy = dog_at(t)
            if not a.dry and not a.mic:
                time.sleep(max(0, t0 + t / a.speed - time.time()))
            ev = {"source": src, "audio_t_s": round(a.offset_s + t, 2), "model": "PANNs CNN14 (zero-shot, AudioSet Bark/Yip/Bow-wow)",
                  "position_from": f"dog stand-in track, run {L['run']}" + (" (SYNTHETIC)" if syn else ""), "synthetic_position": syn}
            if not a.dry:
                inbox.emit("dog1_audio", "dog_bark", float(round(p, 3)), {"x": xx, "y": yy, "frame": "floor"}, None, None, ev)
            n += 1; print(f"  +{t:6.1f}s  dog_bark {p:.2f} at floor ({xx:.1f}, {yy:.1f})")
print(n, "dog_bark events", "(dry run)" if a.dry else "→ night/inbox")
