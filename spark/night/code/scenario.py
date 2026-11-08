"""Demo driver: marks mission start on the fusion chain, replays the latest dog run's alerts into the
inbox at real pace (x --speed), then optionally replays a Tap Three WAV through tap3/live.py.

  python scenario.py                      # dog replay at 4x, then synthetic tap3 near the hidden person
  python scenario.py --speed 1 --no-tap   # real pace, tap live on the table instead (tap3/live.py)
  python scenario.py --tap-wav my.wav     # replay a recorded tap clip
Synthetic material is labelled as such in every inbox record (extra.synthetic=true).
"""
import argparse, json, subprocess, sys, time, urllib.request
from pathlib import Path

N = Path(__file__).resolve().parent
sys.path.insert(0, str(N / "fusion")); sys.path.insert(0, str(N / "tap3"))
import inbox  # noqa: E402


def post(url, d):
    try:
        req = urllib.request.Request(url, data=json.dumps(d).encode(), headers={"content-type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=2).read())
    except Exception as e:
        print("  (fusion not reachable:", e, ")"); return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=4.0)
    ap.add_argument("--no-tap", action="store_true")
    ap.add_argument("--tap-wav")
    a = ap.parse_args()
    runs = sorted(N.glob("data/dog/*/layers.json"), key=lambda p: (json.loads(p.read_text()).get("synthetic", False), -p.stat().st_mtime))
    if not runs:
        sys.exit("no processed dog run: dog/process_run.sh RUN_DIR first")
    L = json.loads(runs[0].read_text()); syn = L.get("synthetic", False)
    print(f"mission start; dog run {runs[0].parent.name}{' (SYNTHETIC)' if syn else ''}, speed x{a.speed}")
    post("http://127.0.0.1:8140/mission_start", {"note": f"scenario.py run={runs[0].parent.name} speed={a.speed}"})
    t0 = time.time(); ts = L["t_start_ms"]
    for al in L["alerts"]:
        if al["confidence"] <= 0 or al["t_ms"] < ts:
            continue
        due = t0 + (al["t_ms"] - ts) / 1000 / a.speed
        time.sleep(max(0, due - time.time()))
        inbox.emit("dog1", al["kind"], al["confidence"], {"x": al["x"], "y": al["y"], "frame": "floor"}, None,
                   extra={"run": runs[0].parent.name, "source": al["source"], "synthetic": syn})
        print(f"  +{(al['t_ms'] - ts) / 1000:6.1f}s  dog1 {al['kind']:12s} ({al['x']:.1f}, {al['y']:.1f})")
    if a.no_tap:
        print("dog replay done. Now tap three on the table: tap3/live.py --x 5.3 --y 3.85"); return
    wav = a.tap_wav
    if not wav:
        import detect, soundfile as sf
        wav = str(N / "tap3/synthetic_taps_demo.wav")
        sf.write(wav, detect.synth_taps(dur=12, tap_times=(1.5, 2.5, 3.5, 7.0, 8.0, 9.0), noise=0.01), 16000)
        print("tap3: replaying SYNTHETIC tap clip (no mic) at the hidden person's position")
    person = L.get("person_truth") or [5.3, 3.85]
    subprocess.run([sys.executable, str(N / "tap3/live.py"), "--wav", wav, "--x", str(person[0]), "--y", str(person[1])])
    print("done: confirm the contact in the fusion console (:8140), then look at the map (:8143) and the AAR")


if __name__ == "__main__":
    main()
