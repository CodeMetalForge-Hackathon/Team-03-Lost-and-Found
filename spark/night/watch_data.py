"""Background watcher: processes real data as soon as it lands, and logs to WORKLOG.md.

  dog runs : any folder with sensors.csv + overhead.mp4 + floor.txt under night/data/dog/ (or under
             ~/projects/Team-3/data/dog/, symlinked in, read-only) that has no layers.json yet
             -> dog/process_run.sh (track, sync, layers). Failures are logged with the error, not retried in a loop.
  taps     : new WAVs under night/data/tap3/ -> tap3/eval.py (rewrites eval_results.json)
Never touches ~/forge/skyfix. Poll every 30 s.
"""
import json, subprocess, time, traceback
from pathlib import Path

N = Path(__file__).resolve().parent
TEAM = Path.home() / "projects/Team-3/data/dog"
PY = str(Path.home() / "forge/.venv/bin/python")
STATE = N / "run/watch_state.json"


def log(msg):
    line = f"- {time.strftime('%H:%M')} — watch — {msg}\n"
    with open(N / "WORKLOG.md", "a") as f:
        f.write(line)
    print(line, end="", flush=True)


def ready(d: Path):
    return all((d / f).exists() for f in ("sensors.csv", "floor.txt")) and \
        any((d / f).exists() for f in ("overhead.mp4", "overhead.MP4", "overhead.mov"))


def main():
    st = json.loads(STATE.read_text()) if STATE.exists() else {"failed": [], "taps": 0}
    while True:
        try:
            if TEAM.exists():
                for d in TEAM.iterdir():
                    if d.is_dir() and d.name.startswith("run_") and ready(d):
                        link = N / "data/dog" / d.name
                        if not link.exists():
                            link.symlink_to(d); log(f"linked real run {d.name} from Team-3 repo")
            for d in sorted((N / "data/dog").iterdir()):
                if not d.is_dir() or (d / "layers.json").exists() or str(d) in st["failed"] or not ready(d):
                    continue
                for alt in ("overhead.MP4", "overhead.mov"):
                    if (d / alt).exists() and not (d / "overhead.mp4").exists():
                        log(f"{d.name}: video named {alt}; expected overhead.mp4 — rename it"); break
                r = subprocess.run(["bash", str(N / "dog/process_run.sh"), str(d)], capture_output=True, text=True, timeout=1800)
                if r.returncode == 0:
                    s = json.loads((d / "sync.json").read_text()); t = json.loads((d / "track_summary.json").read_text())
                    log(f"processed real run {d.name}: sync offset {s['offset_ms']} ms, residual {s['residual_sound_vs_imu_ms']} ms, track methods {t['methods']}")
                else:
                    st["failed"].append(str(d)); log(f"FAILED {d.name}: {(r.stderr or r.stdout)[-300:].strip()}")
            wavs = list((N / "data/tap3").rglob("*.wav"))
            if len(wavs) != st["taps"]:
                time.sleep(20)                  # let a copy finish
                wavs = list((N / "data/tap3").rglob("*.wav"))
                r = subprocess.run([PY, str(N / "tap3/eval.py")], capture_output=True, text=True, timeout=900)
                st["taps"] = len(wavs)
                if r.returncode == 0:
                    tr = json.loads((N / "tap3/eval_results.json").read_text()).get("team_recordings")
                    log(f"tap3 eval on {len(wavs)} team WAVs: {tr}")
                else:
                    log(f"tap3 eval FAILED: {r.stderr[-300:]}")
            STATE.write_text(json.dumps(st))
        except Exception:
            log("watcher error: " + traceback.format_exc()[-300:].replace("\n", " | "))
        time.sleep(30)


if __name__ == "__main__":
    main()
