# ZOOM TO EARTH — final build (AIR → LAND → WATER on one probability map)

You are Claude Code on Franco's DGX Spark at `~/forge`, working interactively with Franco. Code freeze is **Sunday 12:00 ET**;
stop building at **10:30** so the team can rehearse. Work only in `~/forge/zoom/` (new) and `~/forge/night/` (the running
shell: fusion :8140, dog replay :8141, perch :8142, map/COP :8143). Never touch `~/forge/skyfix/` (Sky Fix, :8130/:8131)
or `~/forge/rescuebase-forge/`. Use `~/forge/.venv/bin/python` for everything except the new detector, which needs
`~/forge/zoom/venv_u84/bin/python` (ultralytics ≥ 8.4 for YOLO26 weights). Log to `~/forge/zoom/WORKLOG.md` every 20 min.

Read first: `~/forge/zoom/READINESS.md` (what downloaded; if it is missing, `~/forge/zoom_download.sh` is still running —
check `tmux capture-pane -pt zoomdl | tail`), `~/forge/night/README.md`, `~/forge/night/DEMO_FLOW.md`, `~/forge/night/config.json`.

## The story the demo tells (do not change it)
Zoom in to the Earth. **AIR:** a real hurricane orthomosaic forms on the map as the drone flies; a person detector trained
on aerial search-and-rescue imagery runs over it and over SAR frames; every detection becomes a probability field.
**LAND:** the dog stand-in roams free, its coverage subtracts, its alerts add. **WATER:** a sonar mosaic forms along the
boat's track; a sonar detector trained on a dataset with a human-body class calls out candidates; each call-out becomes a
field over water cells. All of it lands on the one COP the night build already runs, with Next Best Action on top.
**BONUS (already built):** Sky Fix on the phone/glasses for the isolated person.

## Hard rules
- Honesty over polish. Label anything simulated (sonar placement along a borrowed track; victim pins georeferenced from
  non-survey frames) on screen. Never invent terrain pixels: the "generative layer" is captions and depth over the
  mosaic, not inpainting. No fabricated metrics; every number comes from a run you can re-execute.
- Never `pkill`/`kill` by pattern; record PIDs in `zoom/PIDS.txt`. New ports **8150–8159** only.
- GPU: one training job at a time (UATD YOLO11n). vLLM :8001/:8002 may be down; if so use Qwen3-VL via transformers
  only if it loads in < 5 min, otherwise skip captions and say so.
- Time-box every phase. A stub written up honestly beats a half-working piece.

## Phase A — AIR (2 h total)
A1 (30 min) **Disaster ortho base layer.** Load the NOAA tiles in `zoom/air/ortho/noaa_helene/` (fallback: `noaa_ian/`).
Build a small web-tile pyramid (or a single downsampled PNG + world file) and add it as a selectable base layer on :8143
beside Aukerman. Attribution line on screen: "Imagery: NOAA National Geodetic Survey Emergency Response Imagery." Note
the GSD (15–30 cm) on screen and that people are not resolvable at this scale.
A2 (30 min) **Map forming (deterministic).** `zoom/air/stitch_live.py`: incremental OpenCV stitching of a forward flight —
ORB/SIFT features, homography chain, warp into a growing canvas — over the Bellus images (`zoom/air/odm_bellus/images`,
fallback Aukerman). Emit a PNG every N frames so the :8143 "drone replay" shows the map *forming* frame by frame.
Also georeference the final canvas with the EXIF GPS of the first and last frames (two-point affine is fine; label it
"approximate"). Keep the ODM Aukerman ortho as the "fully rectified" comparison.
A3 (30 min) **Person detector, pretrained.** Load `zoom/air/weights/aerialperson/` (YOLO26 n and l; AGPL-3.0, note in
README). Sliced inference at 640 px (SAHI-style tiling) over: the HERIDAL test split (`zoom/air/heridal/`, report
precision/recall against its labels), the Bellus/Aukerman frames, and the NOAA tiles (expect none; report it). Every
detection → the fusion inbox (`night/inbox/`) as `sensor=aerial_rgb` with confidence and position → a field on the COP.
For HERIDAL hits, place them on the map as **"victim pins (georeferenced from SAR frames, simulated placement)"** so the
air layer has visible evidence without lying about the NOAA tiles.
A4 (30 min) **Intelligence over the mosaic (the generative layer, honestly).** For each stitched or NOAA tile: a one-line
caption from Qwen3-VL ("flooded road", "collapsed structure", "debris field") if the model loads; Depth-Anything-V2 relief
as a toggleable 2.5D shading layer. Captions are shown as hazard chips on the tile, never as detections.

## Phase B — WATER (2.5 h total; start the training first so it runs while you do A)
B1 (30 min) **UATD → YOLO.** Convert `zoom/water/uatd/` PASCAL-VOC XML to YOLO labels (10 classes; keep `human body` as
its own class). Train YOLO11n at 640 px, 30 epochs, batch 32, on `~/forge/.venv` ultralytics (not the 8.4 venv), in tmux
`uatd_train`, logging to `zoom/water/train.log`. Time-box 60 min of training; take best.pt. Report per-class mAP50, and
human-body AP separately, in `zoom/water/RESULTS.md`. Fallback if UATD is missing: FDD (`zoom/water/fdd`, class
`victim`) or the `sonar_detector` repo weights if they load.
B2 (45 min) **Sonar mosaic along a track.** `zoom/water/mosaic.py`: read the Red Sea AUV navigation CSV
(`zoom/water/redsea_auv`: timestamp, lat, lon, yaw, depth) — fallback: synthesize a lawnmower track at 3 knots with
heading — and place forward-looking sonar fans (UATD test frames, polar → Cartesian) at each pose, accumulating into a
mosaic raster over water cells. Emit a PNG every N pings so the map shows it forming as the boat moves. Label it
"FLS frames placed along a real AUV track — simulated placement" on screen.
B3 (30 min) **Call-outs.** Run the UATD detector on the frames as they are placed; each `human body` detection → fusion
inbox as `sensor=sonar_fls` → a field over the water cells around the pose; other classes shown as grey markers.
Deterministic callouts (the detector) + the overlay model are the same thing here; say so plainly.
B4 (15 min) Add the water layer toggle to :8143; water cells get their own prior (uniform over the track corridor).

## Phase C — LAND (30 min)
Validate PANNs/AST zero-shot bark/whine/howl on `zoom/land/dog_play_pant` (report accuracy on its labels); wire
`dog_bark` events from the rover's audio (if a mic is attached) or the replay into the inbox with low weight. Everything
else about the dog already works; don't rebuild it. When Rachel and Matteo's real runs land in `night/data/`, the
watcher handles them.

## Phase D — package (30 min)
`zoom/run.sh` starts any new services and prints URLs; update `night/DEMO_FLOW.md` to the new order:
**Sky Fix (phone) → AIR: NOAA ortho forms + detections → LAND: dog run, tap, confirm → WATER: sonar mosaic forms +
human-body call-out → COP layers + Next Best Action → Accept → chain line → AAR.** Keep it inside 10 minutes.
Playwright screenshots of every new screen into `zoom/screenshots/`. README with honest limits and all dataset
attributions (NOAA NGS; AerialPerson-YOLO26 AGPL-3.0; HERIDAL CC BY 3.0; UATD CC BY 4.0; Red Sea AUV Zenodo; Bellus ODM).
Copy README, RESULTS, DEMO_FLOW and screenshots to `~/projects/Team-3/spark/zoom/`, commit "zoom: air/land/water on one
COP — NOAA ortho, aerial-SAR detector, UATD sonar detector, sonar mosaic", push (pull --rebase first; teammates push too).

## Order of work
1. Start B1 training immediately (it is the long pole). 2. A1–A4. 3. B2–B4 when best.pt exists. 4. C. 5. D.
If at 10:00 anything is not working, stub it with an honest README line and ship what runs.
