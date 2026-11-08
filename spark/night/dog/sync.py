"""Align sensors.csv (board clock t_ms), events.csv and overhead.mp4 using the sync_clap.

Clap estimates
  video : loudest transient in the video's audio track (ffmpeg -> 16 kHz mono), searched in the
          first `--search-s` seconds; or `--clap-frame N` if the video has no audio.
  sound : peak of the sound sensor near the typed sync_clap (+-3 s), else in the first search window
  imu   : peak of | |a| - 1 g | near the same time
  typed : the human-typed sync_clap row in events.csv (reported, not used for the offset:
          typing lag is ~0.2-0.5 s)
offset_ms = board_clap_ms - video_clap_s*1000, where board_clap is the mean of sound and imu.
residual  = |sound - imu| (how well the two on-board estimates agree; the bound on alignment).

  python sync.py RUN_DIR [--clap-frame N] [--search-s 30]
Output: RUN_DIR/sync.json
"""
from __future__ import annotations
import argparse, csv, json, subprocess, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vendor"))


def load_sensors(run: Path):
    d = np.genfromtxt(run / "sensors.csv", delimiter=",", names=True, dtype=float)
    return d


def load_events(run: Path):
    p = run / "events.csv"
    if not p.exists():
        return []
    with open(p) as f:
        return [{"t_ms": int(float(r["t_ms"])), "label": r["label"].strip(), "note": (r.get("note") or "").strip()}
                for r in csv.DictReader(f) if r.get("t_ms")]


def video_audio_clap(mp4: Path, search_s: float):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    r = subprocess.run([ff, "-loglevel", "error", "-i", str(mp4), "-t", str(search_s), "-vn", "-ac", "1",
                        "-ar", "16000", "-f", "s16le", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
    if a.size < 1600:
        return None, "no audio track"
    env = np.abs(a)
    k = 80   # 5 ms
    env = np.convolve(env, np.ones(k) / k, "same")
    i = int(np.argmax(env))
    # onset = first sample within 10 ms before the peak where envelope exceeds 50 % of the peak
    j0 = max(0, i - 160)
    on = j0 + int(np.argmax(env[j0:i + 1] > 0.5 * env[i]))
    noise = np.median(env) + 1e-9
    return on / 16000.0, f"audio peak/median = {env[i] / noise:.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--clap-frame", type=int)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--search-s", type=float, default=30.0)
    a = ap.parse_args()
    run = Path(a.run)
    s = load_sensors(run)
    ev = load_events(run)
    t = s["t_ms"]
    typed = next((e["t_ms"] for e in ev if e["label"] == "sync_clap"), None)
    if typed is not None:
        win = (t > typed - 3000) & (t < typed + 3000)
    else:
        win = t < t[0] + a.search_s * 1000
    if win.sum() < 5:
        win = np.ones_like(t, bool)
    snd = s["sound"].astype(float)
    base = np.median(snd[win])
    i_s = int(np.argmax(np.where(win, snd - base, -np.inf)))
    amag = np.sqrt(s["ax"] ** 2 + s["ay"] ** 2 + s["az"] ** 2)
    i_i = int(np.argmax(np.where(win, np.abs(amag - 1.0), -np.inf)))
    t_sound, t_imu = float(t[i_s]), float(t[i_i])
    board = (t_sound + t_imu) / 2
    if a.clap_frame is not None:
        v_clap, how = a.clap_frame / a.fps, f"manual frame {a.clap_frame}"
    else:
        v_clap, how = video_audio_clap(run / "overhead.mp4", a.search_s)
        if v_clap is None:
            raise SystemExit("video has no audio; pass --clap-frame N (the frame where the hands meet)")
    offset = board - v_clap * 1000
    out = {"offset_ms": round(offset, 1), "video_clap_s": round(v_clap, 4), "video_clap_method": how,
           "board_clap_sound_ms": t_sound, "board_clap_imu_ms": t_imu,
           "residual_sound_vs_imu_ms": round(abs(t_sound - t_imu), 1),
           "typed_sync_clap_ms": typed,
           "typed_minus_sensor_ms": None if typed is None else round(typed - board, 1),
           "sensor_rate_hz": round(1000 / np.median(np.diff(t)), 2),
           "note": "board_t_ms = video_t_s*1000 + offset_ms"}
    truth = run / "SYNTHETIC.json"
    if truth.exists():
        tj = json.loads(truth.read_text())
        out["synthetic_true_offset_ms"] = tj["board_offset_ms"]
        out["error_vs_truth_ms"] = round(offset - tj["board_offset_ms"], 1)
    (run / "sync.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
