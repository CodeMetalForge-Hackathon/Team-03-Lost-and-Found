# Sky Fix — a position from the sky, on the phone you already carry

**Pitch.** An isolated aircrew member with no GPS, who must not transmit, still has a phone and a sky.
At night Sky Fix plate-solves a phone photo of the stars and combines it with the phone's own gravity
sensor and clock to get **latitude, longitude, heading and an honest confidence ring**. By day it matches the
mountain **skyline** against a terrain model around the last known fix. Then it gives the **bearing and distance to
a pre-loaded recovery point** on the phone and on Meta display glasses. It is fully offline and emits nothing: every
fix goes into a local hash-chained evidence log and a Cursor-on-Target file that can be handed over later. Our research
found no phone product that turns a star photo into a fix (the Honeywell and Sodern units are aircraft-mounted).

## Run (offline, one command)

```bash
bash ~/forge/skyfix/run.sh            # starts :8130 (HTTP) and :8131 (HTTPS, self-signed), prints URLs
bash ~/forge/skyfix/run.sh stop
bash ~/forge/skyfix/run.sh reset-evidence   # archive (not delete) the evidence log before a demo
```

| URL | what |
|---|---|
| `http://<host>:8130/` | phone app: Night (stars) / Day (skyline), capture, map with ring, bearing to recovery point |
| `http://<host>:8130/?hud=1` | glasses HUD: arrow, distance, ring; shows the latest fix from any device |
| `http://<host>:8130/demo` | judge gallery: synthetic sky, real Pixel photos, Wikimedia, CH1 mountain photos, truth after solving |
| `https://<host>:8131/` | same app over HTTPS. Phones only expose motion sensors to secure pages, so accept the self-signed certificate |

Tests: `~/forge/.venv/bin/python -m pytest -q tests`. Re-run every number in RESULTS.md with
`python eval_stars.py`, `python eval_real.py`, `bash results/run_skyline_test.sh`, `python demo_table.py`.

## How it works

**Night (`solver_stars.py`).** tetra3 centroids, then a plate solve against a 20–70° phone-FOV Hipparcos database.
Fallbacks in order: a centre crop with the shipped 10–30° database, upper-half-only stars (foreground trees and
lights sit at the bottom), an FOV sweep, then a blind solve. A Kabsch fit of the matched stars gives the camera→sky
rotation. With the phone's gravity vector, the zenith is mapped to apparent RA/Dec: lat = Dec, lon = RA − GAST. Three
refraction-aware refinements in the local horizon frame follow. Heading is the camera axis azimuth. The FOV prior
comes from EXIF 35 mm-equivalent focal length, using the diagonal and the true image orientation.

**Day (`solver_skyline.py`).** SAM 2 sky mask, prompted along the top of the frame (fallback: DP gradient path),
gives horizon elevation per column. GLO-30 360° horizon profiles on a 0.5 km grid within ±25 km of the last known
fix (cached; 1 km is the spec baseline). Each cell and heading is scored by the RMS residual after fitting
offset + slope (unknown pitch and small roll). A ratio test against the best cell more than 3 km away flags the fix
as **distinct** or **AMBIGUOUS**.

**Evidence (`evidence.py`).** Reuses `rescuebase-forge`'s append-only SQLite store and CoT builder unchanged, and adds a
SHA-256 chain (`prev_hash` → `hash`). Each fix becomes `cot/SKYFIX-<n>.cot.xml` (type `a-f-G-U-C`, `how=h-e`, `ce` = ring
in metres), validated against the TAK `Marker - 2525.xsd`. Nothing is sent: the UDP sender is never imported.

## Honest limits (read before pitching)

- **The phone's tilt sensor sets the night accuracy, not the stars.** With the exact gravity vector the fix is
  ~0.4 km. With a braced-phone tilt error of 0.3° per axis it is ~40 km (1° of tilt ≈ 111 km). The spec target of
  "≤ 20 km at 0.3°" is not physically reachable with one shot. See RESULTS.md.
- **Real phone photos carry no gravity vector**, so on them we only report sky orientation and never a position.
  The phone-capture path (LOCK TILT, then shoot) has not been tested on a real phone against real stars.
  The accelerometer axis/sign handling follows the W3C spec, with an automatic flip for iOS's opposite sign,
  checked by unit test only and in portrait only.
- **The skyline fix needs a last known fix to ±25 km**, a terrain model of the area (only the Swiss test region is
  loaded) and a clear mountain skyline. Per-photo errors are bimodal: right to ~0.5 km, or confidently wrong. About
  1 in 5 photos gets a **distinct** match, and those are mostly right. The rest are flagged AMBIGUOUS. The spec's
  "median 2–10 km" expectation is not met over all photos.
- The SAM weights on disk are SAM 2 (hiera-small), not 2.1.
- The recovery points in `config/recovery_points.json` are public landmarks for the demo, not mission data.

Files: `app.py` service · `web/` pages · `solver_stars.py` · `solver_skyline.py` · `horizon.py` · `dem.py` · `ch1.py` ·
`synth/render_sky.py` · `evidence.py` · `eval_*.py` · `results/` · `RESULTS.md` · `DEMO_90S.md` · `WORKLOG.md`.
