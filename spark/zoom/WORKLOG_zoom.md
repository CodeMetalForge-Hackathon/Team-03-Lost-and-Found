# Zoom to Earth — WORKLOG (Nov 8, 2026)

Stop building at 10:30. Master prompt: MASTER_PROMPT_ZOOM.md.

## 05:14 start
- Downloads still running (tmux zoomdl). Landed: AerialPerson-YOLO26 weights (sweep n/s/m/l/x + 20 specialists), 5 NOAA Ian tiles, Helene tiles in progress.
- Not landed yet: HERIDAL, Bellus, UATD (queued after HERIDAL/Bellus), Red Sea AUV, FDD, dog audio.
- Services running: night :8140–8143 (PIDs in night/PIDS.txt), Sky Fix :8130/8131 (not touched).
- GPU idle. ultralytics: .venv 8.4.204, venv_u84 8.4.207.
- Plan: write UATD→YOLO converter + train launcher now, start B1 the moment XMLs land; meanwhile A1 (NOAA base layer).

## 05:21 B1 training started
- UATD figshare article-level zip URL returned 0 bytes (download script). Re-fetched the 3 files via the figshare API (scripts/get_uatd.sh, tmux uatddl): Training 3.87 GB, Test_1, Test_2. 9200 XML.
- Converted (water/scripts/uatd_to_yolo.py → water/yolo): train 7600 / val = Test_1 800 / test = Test_2 800 (held out). 10 classes, 'human body' = class 3 (1283 train boxes, 76 val, 73 test). Raw images are polar 1024 beams × 1950 range bins, 120° azimuth.
- GitHub 504 on yolo11n.pt → used local ~/models/yolo/yolo11n.pt. Training in tmux uatd_train, ~35 s/epoch → ~20 min for 30 epochs (60-min box enforced by callback).
- A1: NOAA pyramid builder (air/scripts/build_pyramid.py) → air/tiles/{helene,ian}. Helene: 6 tiles, 1.2×8.3 km, native GSD 9.9 cm. Ian: 5 tiles, 25 cm. Viewer on :8150/air (zoom/serve.py).

## 05:43 B1 done, A2/A3 progress
- B1: YOLO11n UATD 30 ep in 21.1 min. Held-out Test_2: mAP50 0.817, human body AP50 0.910 (val 0.839 / 0.877). water/RESULTS.md, water/uatd_results.json.
- A2: Bellus (dense canopy) does not stitch: 3–13 RANSAC inliers per pair → switched to the prompt's fallback, Aukerman (77 photos, ~/forge/tmp/odm/aukerman/images). SIFT (all features at 0.5 scale) + FLANN + homography to the nearest placed frame: 54/77 placed, looks clean. Georef fit had a y-flip bug (75 m RMS) → fixed, re-running with detections.
- A3: HERIDAL test (101 photos, 337 people), IoU 0.5. 640 px native tiles: AP50 0.07. 1280 px windows → 640 (picked on photos 1–30): held-out 71 photos YOLO26l AP50 0.23 (P 0.55 / R 0.23 at the 0.60 gate), YOLO26n AP50 0.30. Human baseline P 0.59 / R 0.68. air/heridal_eval.json.
- A3 Aukerman: 31 YOLO26l detections at conf ≥ 0.60 → audited by eye: 4 clear people (park visitors), 2 possible, 25 false positives (stop signs, playground equipment). air/aukerman_audit.json.

## 05:50 A2–A4, B2 progress
- A2 done: stitch re-run with the y-flip fix → LSQ georef RMS 18.8 m (2-point 28 m), 54/77 Aukerman frames placed. 20 PNG frames in air/stitch/frames.
- A3: Aukerman detections georeferenced through ODM/OpenSfM camera poses (ray → ground plane, air/georef_odm.py). They agree with the stitch georef to a median of 4.3 m. The 31 conf ≥ 0.60 detections collapse to 8 clusters at 25 m (playground equipment re-detected from many frames).
- A3 NOAA: Ian 555 boxes ≥0.25 / 120 ≥0.60; Helene 961 / 137. Top crops: cars, kayaks, roofs, glint, debris; no person. Shown as unverified, not sent to fusion.
- A4: vLLM :8001/8002 down → Qwen3-VL-4B via transformers (local), running in background (captions.py). Depth not started.
- B2: Red Sea zip is 37.6 GB (at 3.8 GB after 30 min; won't land). Pulled only the navigation/sonar CSVs out of the remote zip with HTTP range requests (water/scripts/remote_zip.py). Track 2023-09-03-11-37-57: 5010 poses, 473 m, 43 min, translated onto Hinckley Lake (largest COP water body, 41.2226 N −81.717 W); 4900/5010 poses land in water. Heading convention auto-picked = NED.
- B2 mosaic: 120 pings with UATD Test_2 frames in file order, 0.2 m/px, 4 s. B3 detector on the same frames: 154 call-outs, 10 human body.

## 06:01 integration on the COP
- night/fusion/fuse.py had a latent bug: the inbox watcher thread died when inbox/processed/ disappeared (an archive moved it) → :8140 had stopped ingesting anything. Fixed (mkdir every pass, guarded rename), backup in zoom/backup_night_0640/, fusion restarted (rebuilds from the chain). night tests 13/13 pass.
- cop.py: new sources aerial / aerial_sim / sonar / water (sonar Gaussian clipped to OSM water cells; water = uniform corridor prior 0.1 × prior once the boat deploys). config.json: aerial_person 0.7, sonar_human_body 0.6, sigmas, corridor. Hand-set.
- :8143: base-layer select (ODM ortho vs live stitch forming with the drone replay), water (sonar) layer + ▶ sonar replay + → lake, HERIDAL victim pins (SIMULATED), 🌀 NOAA disaster layer (inset of :8150/air). Replays emit into night/inbox via :8150 /api/emit/{air,water} (each event once; ↺ resets).
- Verified: after both replays, fusion has 20 contacts (aerial, aerial_sim, sonar_fls). NBA moves to Hinckley Lake: "drone to R379C261, ETA 14.2 min (team 131.4 min)".
- NOTE: test events are in the live chain (plus one duplicate aerial event from the watcher crash). Run ./stop_all.sh && ./run_all.sh before rehearsal (archives, never deletes).
- B3 label check on the 120 placed frames: 10 human-body call-outs, 8 match a label (IoU ≥ 0.5), 9 labelled bodies in those frames.
