# SKY FIX — overnight build (Persona 1: isolated aircrew, no GPS, must not emit)

You are Claude Code, unattended, on Franco's DGX Spark at `~/forge`. Build **Sky Fix**: a GPS-denied
self-localization module with two solvers behind one phone-first web app — **stars by night** (plate-solving)
and **skyline by day** (ridgeline matched to a terrain model) — that returns latitude, longitude when
possible, heading, a confidence ring, and a bearing to a pre-loaded recovery point. The phone is the
primary client; the Meta display glasses show the same page in a minimal HUD mode. Nothing transmits.

Deadline: the time in `~/forge/skyfix/.deadline_human` (default Sunday 09:30 ET). Stop 15 minutes before it.
Code freeze for the hackathon is Sunday 12:00; Franco needs 09:30–11:30 for rehearsal, so do not run past it.

Read first: `~/forge/skyfix/READINESS.md` (what downloaded), `~/forge/logs/download_report.md`,
`~/forge/FORGE_BUILD_SPEC.md` §0–2 (message formats, evidence log), `~/forge/WORKLOG.md` (what exists:
the evidence log, CoT output via PyTAK, the phone HUD fallback). Reuse the evidence log and CoT code from
`~/forge/rescuebase-forge`; do not rewrite them.

## Why this matters (so you make the right trade-offs)
Judges score Relevance, Working live demo, Deployability, Ideation (25% each). Every mentor validated
"navigate by the stars and the ridgeline, on the thing you already carry." The competitive research found
no phone product that turns a star photo into a fix (Honeywell/Sodern are aircraft-mounted; Skyline Nav AI
took a $750k AFRL contract in 2022 and never shipped on a phone). The demo is at noon indoors and it is
cloudy, so the live demo runs on **photos with known location** and a **synthetic sky** with exact ground
truth. Honesty beats polish: a km-class fix with a drawn confidence ring wins; a fake metre-class fix loses.

## Hard rules
- Work only under `~/forge/skyfix/`. Never modify `~/forge/rescuebase-forge`, `~/models`, or the SSD (read and copy in is fine).
- Never run `pkill`/`kill` with a pattern. Only kill PIDs you started and recorded in `skyfix/PIDS.txt`.
- GPU: inference only. vLLM may be running on :8001/:8002; never stop it. SAM 2.1 for sky masks is allowed.
- Ports: **8130–8139** only. Record in `skyfix/PORTS.md`.
- Log to `~/forge/skyfix/WORKLOG.md` every 20 minutes: time, phase, what works, what failed, next step.
- Time-box each phase as stated. If a phase is not working at its time-box, write what is missing in
  WORKLOG.md and move on. A working star solver with no skyline beats two half-solvers.
- Everything must run offline from a fresh shell with one command: `bash ~/forge/skyfix/run.sh`.
- No fabricated accuracy numbers. Every number in the report comes from a run you can re-execute.

## Phase 0 — ground truth you can trust (30 min)
1. Confirm `skyfix/data/stars/phone_fov70_db.npz` exists (built by `skyfix_prepare.sh`). If not, build it:
   tetra3 `generate_database(max_fov=70, min_fov=20, star_catalog='hip_main', star_max_magnitude=7)`
   with `hip_main.dat` copied into the tetra3 package `data/` dir. Also keep the shipped default DB
   (10–30° FOV) for the **centre-crop fallback**.
2. Write `skyfix/synth/render_sky.py`: given lat, lon, UTC, azimuth, altitude, roll, horizontal FOV, image size,
   render a star field from Hipparcos (astropy `SkyCoord` → `AltAz` → pinhole projection; magnitude → Gaussian
   PSF brightness; add Poisson noise, a sky-glow gradient, and optional 3% random dropouts to imitate phone
   noise reduction). Save PNG + a JSON sidecar with every parameter. Generate **60 frames**: 10 locations
   (include Boston 42.36,-71.06 and a mountain site 46.5,8.0), 3 headings, 2 altitudes (35°, 60°), FOV 70°.
3. Index the real photos: `skyfix/data/sky_photos/index.json` (Wikimedia, geotagged, timestamped, CC) and
   `skyfix/data/stars/astrosmartphone/` (unzip; read EXIF with exifread; keep only files with DateTimeOriginal;
   note which have GPS). Write `skyfix/data/PHOTO_INDEX.md` with counts.

## Phase 1 — star solver (90 min)
`skyfix/solver_stars.py`:
- Input: image path or bytes, UTC (from EXIF or request), optional gravity vector (ax, ay, az in camera frame),
  optional FOV estimate.
- Detect stars (tetra3 `get_centroids_from_image`), solve with the phone-FOV DB; on failure, centre-crop to
  ~30° and solve with the default DB; on failure, try `fov_estimate` sweep 50/60/70/80.
- Output: RA/Dec of image centre, roll, FOV, number of matched stars, solve time, plus:
  - **If a gravity vector is given:** compute the zenith direction in the camera frame, map it through the
    solved orientation to RA/Dec; then latitude = Dec(zenith), longitude = RA(zenith) − GMST(UTC) (wrap to
    ±180). Heading = azimuth of the camera's forward axis from the same orientation. Report an error ring:
    1° of zenith-direction error ≈ 111 km, so ring_km = 111 × (centroid_rms_deg + tilt_sigma_deg); use
    tilt_sigma 0.3° braced, 1.4° handheld (Grm & Grm 2021) unless the request says otherwise.
  - **If no gravity vector:** return sky orientation only and say plainly "no latitude without the phone's
    gravity vector" — do not guess.
- Acceptance on the 60 synthetic frames (gravity vector = exact): solve rate ≥ 90%, median position error
  ≤ 20 km with 0.3° tilt noise added. Report the numbers in `skyfix/RESULTS.md`. Then run on the real photo
  sets and report solve rate (real photos have no gravity vector: report "sky orientation solved" rate and,
  where the photo's EXIF has time and the horizon is visible, say so).

## Phase 2 — skyline solver (90 min)
`skyfix/solver_skyline.py`:
- Load CH1 (`skyfix/data/skyline/CH1/`): read each image's ground-truth lat/lon and FOV from the metadata
  files shipped with the set (inspect them first; document the format in WORKLOG.md).
- Horizon extraction: SAM 2.1 (on disk) prompted on the top-centre of the image for the sky mask; fallback
  to a gradient + row-wise sky/ground split. Output: horizon elevation angle per image column, using the FOV.
- Terrain horizons: from the GLO-30 tiles in `skyfix/data/dem/`, pre-render 360° horizon profiles
  (elevation angle per 1° of azimuth, max over range up to 60 km) on a **1 km grid within ±25 km of the true
  location** (the aircrew persona knows its last fix to tens of km, so a constrained search is honest; say so).
  Cache to `skyfix/cache/`.
- Match: 1-D cross-correlation of the photo horizon against each candidate's profile over all azimuth
  offsets (handles unknown heading); score = correlation; return the best cell, the heading, and a
  confidence ring = the radius containing the top-5% of scores.
- Acceptance: run on ≥ 20 CH1 images; report median and 75th-percentile position error in km and the
  fraction within 5 km. Honest expectation: median 2–10 km. Do not tune on the test images.

## Phase 3 — the phone app + glasses HUD + evidence log (90 min)
FastAPI service `skyfix/app.py` on :8130 serving a single-page PWA at `/`:
- **Capture**: `<input type=file accept=image/* capture=environment>` (works on iPhone Safari) plus a
  "Use this photo" picker for the demo sets; read DeviceMotion gravity (request permission on iOS) and
  the clock at capture; a toggle Night (stars) / Day (skyline).
- **Result**: map (Leaflet with locally cached tiles or a plain canvas) with the fix, the confidence ring,
  a heading needle, and the bearing + distance to the **pre-loaded recovery point** (config file with
  primary/alternate/contingency points). Big text, high contrast.
- **HUD mode** (`/?hud=1`): minimal layout for the glasses: bearing arrow, distance, confidence, nothing else.
- **Evidence**: every fix is appended to the existing hash-chained evidence log (reuse the code in
  `rescuebase-forge`) and emitted as a CoT event file (type `a-f-G-U-C`, uid `SKYFIX-<n>`, `ce` = ring metres),
  validated against `~/forge/datasets/cot/cotlib` XSD if present. Nothing is transmitted; files only.
- `/demo` page: a gallery of the synthetic frames, the Wikimedia photos and 10 CH1 photos with "Solve"
  buttons and the known truth shown after solving, so the judges see error, not just a pin.
- Playwright screenshots of `/`, `/?hud=1`, `/demo` into `skyfix/screenshots/`.

## Phase 4 — package and report (30 min)
- `skyfix/run.sh` starts the service and prints the URLs; `skyfix/README.md` (pitch paragraph, how to run,
  honest limits); `skyfix/DEMO_90S.md` (exact clicks for a 90-second demo: synthetic night frame → fix →
  bearing; CH1 day photo → fix with ring; show the evidence log line).
- `skyfix/RESULTS.md` with the numbers from Phases 1 and 2, the solve times, and a "what would make it
  metre-class" paragraph (gyro-stabilized exposure, multi-frame, known lens model).
- Copy `README.md`, `RESULTS.md`, `DEMO_90S.md` and the screenshots into `~/projects/Team-3/spark/skyfix/`,
  `git add -A && git commit -m "skyfix: overnight build" && git push` from `~/projects/Team-3`.
- Write `~/forge/skyfix/MORNING_REPORT.md` and `touch ~/forge/skyfix/.ALL_DONE`.

## Stretch (only if everything above is green)
- Breadcrumb: dead-reckon between fixes from DeviceMotion step counts + compass, drawn as a dotted trace.
- Render a 10-second video of the HUD for the pitch deck (Playwright + ffmpeg).
- Second skyline area: pre-render around Boston for the Blue Hills using N42W072 (download it if online).
