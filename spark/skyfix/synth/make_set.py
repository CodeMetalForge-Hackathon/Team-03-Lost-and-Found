"""Generate the 60-frame synthetic evaluation set: 10 sites x 3 headings x 2 altitudes, HFOV 70 deg.
Each frame at local solar midnight on 2026-11-08 (UTC = 00:00 - lon/15 h), with a seeded small handheld roll.
Output: synth/frames/*.png + .json, synth/frames/manifest.json."""
import json, pathlib, sys
from datetime import datetime, timedelta, timezone
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from render_sky import render, save

SITES = [  # name, lat, lon, elevation m
    ("boston", 42.36, -71.06, 10), ("swiss_alps", 46.5, 8.0, 1800), ("fort_bragg", 35.14, -79.0, 90),
    ("mojave", 35.0, -116.5, 900), ("anchorage", 61.2, -149.9, 40), ("hindu_kush", 34.5, 69.2, 1800),
    ("sahara", 23.6, 5.0, 600), ("sydney", -33.9, 151.2, 50), ("patagonia", -50.3, -72.3, 300),
    ("mauna_kea", 19.8, -155.5, 2500)]
HEADINGS = [30.0, 150.0, 270.0]
ALTS = [35.0, 60.0]
OUT = pathlib.Path(__file__).resolve().parent / "frames"


def main():
    rng = np.random.default_rng(20261108)
    manifest = []
    for name, lat, lon, elev in SITES:
        hrs = (-lon / 15.0) % 24
        utc = (datetime(2026, 11, 8, tzinfo=timezone.utc) + timedelta(hours=hrs)).replace(microsecond=0)
        for az in HEADINGS:
            for alt in ALTS:
                roll = float(np.round(rng.normal(0, 6), 2))
                seed = int(rng.integers(1 << 30))
                fn = OUT / f"{name}_az{int(az):03d}_alt{int(alt):02d}.png"
                dn, meta = render(lat, lon, utc.strftime("%Y-%m-%dT%H:%M:%S"), az, alt, roll, 70.0,
                                  elevation_m=elev, seed=seed)
                meta["site"] = name
                save(dn, meta, fn)
                manifest.append({"file": fn.name, **{k: meta[k] for k in ("site", "lat", "lon", "utc", "az", "alt", "roll", "n_stars_rendered")}})
                print(fn.name, meta["n_stars_rendered"], flush=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
