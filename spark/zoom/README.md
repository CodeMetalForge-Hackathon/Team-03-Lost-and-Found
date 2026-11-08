# Zoom to Earth: AIR → LAND → WATER on one probability map

Built Sunday Nov 8, 2026, 05:10–06:15 ET, on the DGX Spark. It extends the night shell (`~/forge/night`, ports 8140–8143). Sky Fix (`~/forge/skyfix`) was not touched.

```bash
cd ~/forge/night && ./stop_all.sh && ./run_all.sh     # fresh evidence chain (archives the old one, never deletes)
bash ~/forge/zoom/run.sh reset                        # starts :8150 if needed, forgets emitted AIR/WATER events, prints URLs
```
| port | screen |
|---|---|
| 8150/air | NOAA disaster orthomosaic (Helene, Ian) with person-detector boxes, hazard chips, 2.5D relief; "▶ map forming" stitch replay |
| 8150/water | sonar mosaic forming along the boat track, raw FLS frame + detector, call-outs |
| 8143 | the COP. New: base select (ODM ortho / live stitch), **water (sonar)**, **▶ sonar replay**, **→ lake**, **🌀 NOAA disaster layer**, HERIDAL victim pins, 4 new COP sources |

## What runs, and the numbers (each from a run you can repeat)

### AIR
- **NOAA base layer** (`air/scripts/build_pyramid.py`): NOAA NGS Emergency Response Imagery GeoTIFFs. They are turned into a 512 px WebP pyramid plus an overview PNG and world file.
  - **Helene**, 27 Sep 2024: 6 tiles, 1.2 × 8.3 km of the St. Joseph peninsula (FL), native GSD **9.9 cm**.
  - **Ian**, 2 Oct 2022: 5 tiles around Charleston SC, **25 cm**.
  - These places are not the Ohio search grid. The screen says so, and :8143 shows them as an inset.
- **Map forming** (`air/stitch_live.py`): deterministic OpenCV pipeline. SIFT features (all of them, at 0.5 scale) are matched with FLANN. Each photo gets a RANSAC homography to the nearest already-placed photo (by EXIF GPS) and is warped into a growing canvas, with a PNG every 4 photos.
  - **Bellus does not stitch.** It is dense forest canopy with 3–13 inliers per pair, so the prompt's fallback **Aukerman** (77 photos, inside the COP grid) is used.
  - **54/77 photos placed.** Georeference: a least-squares similarity from the photo centres to EXIF GPS, **RMS 18.8 m** (a 2-point first/last fit gives 28 m). It is labelled approximate.
  - The ODM orthophoto stays as the fully rectified comparison (base select on :8143).
- **Person detector** (`air/detect_air.py`, `air/eval_heridal.py`): AerialPerson-YOLO26 (AGPL-3.0, Ultralytics 8.4 in `venv_u84`), sliced inference.
  - **HERIDAL test** (101 photos, 337 people, IoU 0.5):
    - 640 px native windows give AP50 **0.07**.
    - 1280 px windows resized to 640 (picked on photos 1–30), on the held-out photos 31–101:
      - **Deployed model, YOLO26l at the 0.60 gate: AP50 0.23, P 0.55, R 0.23.**
      - YOLO26n: **AP50 0.30**.
    - **Published human baseline** (human observers on HERIDAL, not a model): P 0.59 / R 0.68.
  - **Aukerman** (`air/aukerman_audit.json`): 31 boxes at conf ≥ 0.60. Checked by eye, 4 are clearly people (park visitors in 2016), 2 are possibly people, and **25 are false positives** (stop signs, playground equipment).
    - They are georeferenced through ODM/OpenSfM camera poses (ray to ground plane, `air/georef_odm.py`), which agrees with the stitch to a median of 4.3 m.
    - The 31 boxes collapse to 8 clusters at 25 m.
  - **NOAA**: Ian has 120 boxes at ≥ 0.60 and Helene 137. Looking at the top 12: cars, kayaks, roofs, glint, debris, no person. A person is 2–5 px at this GSD. The boxes are shown as unverified and **not** sent to fusion.
- **Victim pins (SIMULATED placement)** (`air/build_events.py`): the 5 highest-confidence HERIDAL true positives, shown at Aukerman photo positions. They form their own COP source, `aerial_sim`, which can be unticked.
- **Hazard chips** (`air/captions.py`): vLLM was down, so Qwen3-VL-4B runs through transformers (loads in 47–51 s). It gives one closed-vocabulary label per ~400 m tile.
  - The first prompt ("after a hurricane") labelled every tile as damage, so it was rewritten neutrally.
  - **Spot check: about 2 of 10 hazard chips are plausible.** The layer is **off by default** and labelled unvalidated. Captions are never detections.
- **2.5D relief** (`air/depth_relief.py`): Depth-Anything-V2-Small, normalised per tile, drawn as shading. It is not elevation.

### WATER
- **UATD → YOLO11n** (`water/RESULTS.md`): 7600 train / 800 val (Test_1) / 800 held-out test (Test_2), 30 epochs in 21.1 min.
  - **Test_2: mAP50 0.817, human body AP50 0.910** (val 0.839 / 0.877).
  - The human body is a submerged dummy, and the test frames come from the same campaign as training (in-distribution).
- **Sonar mosaic** (`water/mosaic.py`), "FLS frames placed along a real AUV track — SIMULATED placement":
  - The real ALICE-AUV navigation (Red Sea, Zenodo 10544811; 5010 poses, 473 m, 43 min) is translated onto **Hinckley Lake**, the largest water body on the COP grid. 4900/5010 poses fall in water.
  - The Red Sea archive is 37.6 GB, so only the navigation CSVs were read out of the remote zip with HTTP range requests (`water/scripts/remote_zip.py`).
  - UATD Test_2 frames are placed in file order, polar → Cartesian fans, 0.2 m/px.
- **Call-outs**: the detector runs on each placed frame and gives 154 call-outs, 10 of them human body.
  - **8 of the 10 match a labelled body (IoU ≥ 0.5)**, and 9 bodies are labelled in those frames.
  - Human-body call-outs go to fusion as `sonar_fls` and become Gaussians **clipped to water cells**. The other classes are grey markers.
  - Here the detector *is* the overlay.
- **Water prior**: once the boat deploys, the water cells within 60 m of the track get a uniform corridor prior of 0.1 × the prior's mass (hand-set).

### LAND (`land/RESULTS.md`)
- Zero-shot PANNs and AST on Dog play pant (2636 expert-labelled segments).
  - **Bark vs everything else: AUC 0.988 (PANNs) / 0.984 (AST).** PANNs at 0.5 gives P 0.61 / R 0.75.
  - Whine, growl and pant are weak, and "dog present" vs human is only AUC 0.64–0.70.
  - **Howl: no label in the dataset, not validated.**
- `land/bark_live.py` drops `dog_bark` events (weight lowered to 0.3) from a mic or a labelled REPLAY at the dog stand-in's position. No mic is attached tonight.

### On the COP (:8143)
- The drone replay emits each AIR event into `night/inbox` when the replay passes that photo's capture time. The sonar replay emits each human-body call-out when its ping is placed (`:8150/api/emit/*`, once each; ↺ resets).
- New sources: `aerial`, `aerial_sim`, `sonar`, `water`. Each can be shown, unticked, and is capped at 1.0 × the prior's mass like every other source.
- After both replays, the Next Best Action moves to the lake: "drone to R379C261, ETA 14.2 min (team 131.4 min)".

## Changes to the night shell
All backed up in `zoom/backup_night_0640/`.
- `fusion/fuse.py`: **bug fix.** The inbox watcher thread died for good if `inbox/processed/` disappeared (an archive had moved it), and :8140 silently stopped ingesting. It now re-creates the folders on every pass and never dies on a failed rename. Night tests: 13/13 pass.
- `map/cop.py`, `map/serve.py`, `map/index.html`, `config.json`: the new sources, layers and controls above. New weights: aerial_person 0.7, sonar_human_body 0.6. dog_bark went from 0.5 to 0.3.

## Honest limits
- The sonar placement and the victim-pin placement are **simulated** and labelled so on every screen.
- NOAA tiles are not the search area, and the detector does not find people in them.
- The stitch georeference is ±~20 m.
- The Aukerman detections are mostly playground equipment.
- The hazard chips are mostly wrong.
- UATD is in-distribution.
- The bark validation comes from lab recordings.
- Field widths and weights are hand-set.
- **Not verified:** whether the HERIDAL test photos are excluded from AerialPerson-Mix's training data.
- No terrain pixels are generated anywhere. The "generative" layer is only captions and depth over the real imagery.

## Attributions
- NOAA National Geodetic Survey, Emergency Response Imagery (public domain, US Government). "Imagery: NOAA National Geodetic Survey Emergency Response Imagery."
- AerialPerson-YOLO26 (alejp1998, Hugging Face; Zenodo 10.5281/zenodo.20643213): **AGPL-3.0** weights. The AerialPerson-Mix labels are CC BY 4.0. Running them here puts the detector service under AGPL terms if distributed.
- HERIDAL (Božić-Štulić et al.; test split via github.com/Drivera0/sightline): **CC BY 3.0**.
- UATD (Xie et al. 2022, figshare 21331143): **CC BY 4.0**.
- Red Sea ALICE-AUV FLC/FLS dataset (Zenodo 10544811): **CC BY 4.0** (navigation CSVs only).
- OpenDroneMap sample data: odm_data_bellus (**CC0**; tried, did not stitch) and odm_data_aukerman (used; licence per the OpenDroneMap repository, not re-checked tonight).
- Dog play pant (BARKS Lab, ELTE; Zenodo 18972388): **CC BY 4.0**.
- Models: Ultralytics YOLO11n (AGPL-3.0), Qwen3-VL-4B-Instruct (Apache-2.0), Depth-Anything-V2-Small (Apache-2.0), PANNs CNN14 (MIT), AST AudioSet (BSD-3).
- OSM © OpenStreetMap contributors.
