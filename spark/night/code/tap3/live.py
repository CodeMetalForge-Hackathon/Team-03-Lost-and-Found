"""Live Tap Three: microphone -> rolling buffer -> detect.py -> JSON lines + 3 s WAV clip + inbox.

Sources (first that works): --wav FILE (replayed in real time, for demos/tests), sounddevice,
arecord (ALSA). Output: one JSON line per event on stdout and appended to night/tap3/events.jsonl;
the raw clip around each event saved under night/tap3/clips/. Confirmed events go to the fusion inbox.

  python live.py                       # default mic
  python live.py --device hw:1,0       # arecord device
  python live.py --wav test.wav        # replay a file as if live
  python live.py --x 3.0 --y 2.0       # sensor position for the inbox (metres, local frame)
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "fusion"))
from detect import detect  # noqa: E402
import inbox  # noqa: E402

FS = 16000
BUF_S = 14.0      # enough for two patterns at 1.5 s gaps plus guards
STEP_S = 0.5


def chunks_from_wav(path, realtime=True):
    x, fs = sf.read(path, always_2d=False)
    if x.ndim > 1: x = x.mean(1)
    if fs != FS:
        from scipy.signal import resample_poly
        x = resample_poly(x, FS, int(fs))
    n = int(STEP_S * FS)
    for i in range(0, len(x), n):
        if realtime: time.sleep(STEP_S)
        yield x[i:i + n].astype(np.float32)
    # flush with silence so trailing patterns clear their guard window
    for _ in range(int(4 / STEP_S)):
        yield np.zeros(n, np.float32)


def chunks_from_sounddevice(device=None):
    import sounddevice as sd  # optional
    n = int(STEP_S * FS)
    with sd.InputStream(samplerate=FS, channels=1, dtype="float32", device=device) as s:
        while True:
            d, _ = s.read(n); yield d[:, 0]


def chunks_from_arecord(device=None):
    cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(FS), "-c", "1", "-t", "raw"]
    if device: cmd += ["-D", device]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n = int(STEP_S * FS) * 2
    while True:
        b = p.stdout.read(n)
        if not b: raise RuntimeError("arecord produced no audio (no capture device?)")
        yield np.frombuffer(b, np.int16).astype(np.float32) / 32768.0


def run(chunks, x_m=None, y_m=None, sensor="tap3", realtime_clock=True):
    clips = HERE / "clips"; clips.mkdir(exist_ok=True)
    log = (HERE / "events.jsonl").open("a")
    buf = np.zeros(0, np.float32); consumed = 0.0  # seconds dropped off the buffer front
    seen = set(); t0 = time.time()
    for c in chunks:
        buf = np.concatenate([buf, c])
        if len(buf) > BUF_S * FS:
            drop = len(buf) - int(BUF_S * FS); buf = buf[drop:]; consumed += drop / FS
        r = detect(buf, FS)
        for e in r["events"]:
            t_abs = consumed + e["t"]
            # an event is final once its guard window (1.5 x gap) is inside the buffer
            if e["t"] + 1.5 * e["interval"] > len(buf) / FS - 0.05:
                continue
            key = (e["kind"], round(t_abs, 1))
            if key in seen: continue
            seen.add(key)
            s0 = max(0, int((e["t"] - 3.0 + 0.3) * FS)); s1 = min(len(buf), s0 + 3 * FS)
            wall = t0 + t_abs if realtime_clock else time.time()
            clip = clips / f"{wall:.3f}_{e['kind']}.wav"
            sf.write(clip, buf[s0:s1], FS)
            rec = {"timestamp": round(wall, 3),
                   "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(wall)),
                   "stream_t": round(t_abs, 3), "kind": e["kind"], "interval_s": e["interval"],
                   "confidence": e["confidence"], "clip": str(clip)}
            print(json.dumps(rec), flush=True); log.write(json.dumps(rec) + "\n"); log.flush()
            if e["kind"] == "confirmed":
                pos = {"x": x_m, "y": y_m} if x_m is not None else {}
                inbox.emit(sensor, "tap_pattern_3", e["confidence"], pos, str(clip), t=wall,
                           extra={"interval_s": e["interval"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav"); ap.add_argument("--device"); ap.add_argument("--fast", action="store_true")
    ap.add_argument("--x", type=float); ap.add_argument("--y", type=float)
    a = ap.parse_args()
    if a.wav:
        src = chunks_from_wav(a.wav, realtime=not a.fast)
    else:
        try:
            import sounddevice  # noqa
            src = chunks_from_sounddevice(a.device)
        except Exception:
            src = chunks_from_arecord(a.device)
    try:
        run(src, a.x, a.y)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
