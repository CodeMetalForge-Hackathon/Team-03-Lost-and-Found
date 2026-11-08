# FORGE NIGHT BUILD — the shell and its live sensors (runs beside the Sky Fix session)

You are Claude Code on Franco's DGX Spark at `~/forge`, working interactively with Franco. Another Claude Code
session is building **Sky Fix** in `~/forge/skyfix/` right now (tmux `skyfix`). **You never touch that folder.**
You build everything else the pitch needs, under `~/forge/night/`, reusing the overnight RescueBase build in
`~/forge/rescuebase-forge` (read-only; copy what you need into `night/`).

Hackathon: Code Metal Forge 2026, "Operation Lost and Found" — personnel recovery with no GPS, no cell, in
contested or disaster environments. Judged 25% each on Relevance, Working live demo, Deployability, Ideation.
Code freeze Sunday 12:00 ET. Stop building at 09:30 so Franco can rehearse; after that, only fixes he asks for.

Read first: `~/forge/FORGE_BUILD_SPEC.md` §0–2, `~/forge/WORKLOG.md` (what pass 1/2 built: fusion, evidence
store `rb/store.py`, CoT via PyTAK, phone HUD fallback, replay), `~/forge/logs/download_report.md`,
`~/projects/Team-3/docs/DOG_HANDOFF.md` (the data contract Rachel and Matteo are recording to tonight).

## The architecture you are completing
**Trace Fusion is the shell.** Its live sensors are Tap Three (contact mic), Perch and Listen (acoustic
classifier), thermal YOLO (already built), and the **dog stand-in** (a small rover carrying an IMU + sound-level
+ ultrasonic rig, tracked by an overhead phone camera). **Persona Search Map + Clue Engine** is the one screen the
shell searches against. Every detection → contact with confidence → human confirm → CoT pin → hash-chained
evidence log → AAR. Sky Fix (the other session) is the Persona 1 phone module and shares the map.

## Hard rules
- Work only in `~/forge/night/`. Read anything; write nowhere else except `~/projects/Team-3/` at the end.
- Never `pkill`/`kill` by pattern; record PIDs you start in `night/PIDS.txt`. Ports **8140–8149** only (`night/PORTS.md`).
- GPU inference only; vLLM on :8001/:8002 stays up. The one allowed training job is the AST/PANNs linear probe (Phase 3).
- Python: `~/forge/.venv/bin/python` (system python3 has no numpy). `git-lfs` is not installed; SAREnv's data is missing (code is present) — do not depend on it.
- Log to `~/forge/night/WORKLOG.md` every 20 minutes. Time-box each phase; a stub is written up honestly and skipped.
- No fabricated numbers. Every figure in a README comes from a run you can re-execute.
- Ask Franco before anything irreversible or anything that needs hardware he has to plug in.

## Phase 1 — Tap Three detector (45 min)
`night/tap3/`: `detect.py` (spectral-flux onset detection → accept when 3 onsets fall within ±15% of a constant
interval between 0.5 and 1.5 s and nothing else is in the window; require the pattern twice for a "confirmed"
event), `live.py` (microphone stream via sounddevice or arecord → events as JSON lines with timestamp, interval,
confidence, and the 3-second raw clip saved as WAV), `eval.py` on the negatives: ESC-50 `door_wood_knock` and
`footsteps` (on disk) + `~/forge/datasets/vibration/footstep_8env.mat` (geophone). When Franco's recorded taps land
in `~/forge/night/data/tap3/` (30 positive / 30 negative, 10 s WAVs, see handoff), run eval and report hit rate
and false alarms per hour in `night/tap3/RESULTS.md`. Emit each confirmed event into the fusion inbox (Phase 4).

## Phase 2 — Dog stand-in ingest (60 min)
`night/dog/`: implements the DOG_HANDOFF data contract exactly.
- `track_overhead.py`: overhead video + `floor.txt` (four markers, measured spacing) → homography → dog XY in metres
  at 30 fps by tracking the bright marker (OpenCV HSV threshold + centroid; fall back to background subtraction).
- `sync.py`: align `sensors.csv` (board clock `t_ms`), `events.csv`, and the video using the `sync_clap` (sound spike +
  IMU jolt + video frame). Report alignment offset and residual.
- `layers.py`: coverage cells swept (grid 0.5 m, POD by dwell), alert events (`dog_stop`, `dog_spin`, sound spikes),
  ultrasonic occupancy map (`us_cm` along the track), all time-stamped.
- `replay.html` on :8141: scrub-able timeline; cells shade as covered; alert pins drop; the searched area subtracts
  from the persona grid (Phase 5). Until real runs arrive, generate a synthetic run (`make_synthetic_run.py`) so the UI is
  demoable, and label it SYNTHETIC on screen.

## Phase 3 — Perch and Listen (45 min)
`night/perch/`: pick one DroneAudioSet configuration (volume 80%, room1, drone1, speaker 1 m, mic3_8array-up) and
pull the same clip from `source-only` (rotors off = perched) and `drone-with-source` (in flight). `tag.py` runs
AST and PANNs on both and prints the top tags (Speech / Shout / Screaming vs noise). `demo.html` on :8142: play
noisy → "land, cut rotors" → clean, tags live on both. **Optional training (background, ≤ 2 h):** linear probe on
frozen AST embeddings, 3 classes HV / HNV / NH, split by room and drone, on a few thousand 1–10 s windows; report
F1 per class in `night/perch/RESULTS.md`. If the subset layout is unclear, read `~/forge/repos/DroneAudioSet-code`.

## Phase 4 — Fusion inbox + evidence log + CoT (45 min)
`night/fusion/`: a file-drop inbox (`night/inbox/*.json`) that every sensor writes to: `{t, sensor, kind, position
(x,y or lat,lon), confidence, clip_path}`. `fuse.py` clusters by position and time → contacts with noisy-OR
confidence; `confirm` endpoint flips a contact to confirmed with the operator's id; every event hashed with the
previous hash (SHA-256 chain) into `night/evidence/chain.jsonl`, and each confirmed contact written as a CoT XML
(`a-h-G`, `ce` = uncertainty metres) validated against the XSD in `~/forge/datasets/cot/cot-validator/validator/schemas`.
Reuse `rb/store.py` from rescuebase-forge if it fits; add the chain on top. `aar.py` prints time-to-first-contact,
time-to-confirm, area covered, probability captured per hour.

## Phase 5 — Persona Search Map + Clue Engine, one screen (60 min)
`night/map/` on :8143. Without SAREnv's data, build the prior directly: OSM features from
`~/forge/datasets/osm/ohio-latest.osm.pbf` (pyrosm or osmium; roads, trails, water, buildings) within 10 km of the
Aukerman ortho (DEM `~/forge/skyfix/data/dem/N41W082.tif` — read-only), × persona distance rings from Koester 2020 (use
these published percentiles: autistic temperate 25/50/75/95% = 0.4/0.9/2.3/8.0 km; typical child 1–16 temperate =
0.3/0.9/2.4/11.3 km; label hiker/hunter/dementia as "illustrative"). Persona switcher re-weights (autistic → structures
and water up, trail offset tight). Clue Engine: form with clue type + photo → posterior ∝ prior × LR(cell), LR from a
hand-built table of 6–8 clue types with a provenance string shown next to every update ("expert prior; Koester 2020
POD table"); optional Qwen3-VL on :8002 proposes the clue type, human confirms. Dog coverage from Phase 2 subtracts.
Show uncertainty per cell. Cite Hill 2012 (78% of planners subadditive) in the page footer as the reason the map normalizes.

## Phase 6 — package (30 min)
`night/run_all.sh` starts every service and prints URLs; `night/README.md` (one paragraph per piece, honest limits,
how to run); `night/DEMO_FLOW.md` (the 10-minute pitch order: Sky Fix phone → dog runs, cells shade → tap three
on the table, pin drops → perch clip contrast → map re-ranks → evidence log and AAR); Playwright screenshots into
`night/screenshots/`. Copy README, DEMO_FLOW, RESULTS files and screenshots into `~/projects/Team-3/spark/night/`;
commit and push. Append a status table to the repo README.

## If Franco gives you something mid-stream
Real dog runs → re-run Phase 2 on them and replace the synthetic run. Real taps → re-run Phase 1 eval.
Sky Fix results → link them from DEMO_FLOW.md; do not edit `~/forge/skyfix/`.
