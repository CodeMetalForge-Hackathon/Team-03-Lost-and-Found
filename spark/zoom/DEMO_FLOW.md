# 10-minute demo flow: Zoom to Earth (AIR → LAND → WATER on one COP)

**Before judges arrive (3 min):**
1. `cd ~/forge/night && ./stop_all.sh && ./run_all.sh` gives a fresh evidence chain (the old one is archived, never deleted).
2. `bash ~/forge/zoom/run.sh reset` starts the zoom screens on :8150, forgets already-emitted AIR/WATER events, and prints URLs.
3. Sky Fix: `bash ~/forge/skyfix/run.sh reset-evidence && bash ~/forge/skyfix/run.sh`, following `~/forge/skyfix/DEMO_90S.md`.
4. Open tabs in this order: Sky Fix `:8130`, AIR `:8150/air`, map `:8143`, dog replay `:8141`, fusion `:8140`, WATER `:8150/water`.
5. Map: persona **Autistic**, layer **COP**, base **ODM orthophoto**, press ⌂ IPP and both **↺** buttons (drone and sonar not flown yet).
6. If a mic is plugged in, test one tap-three with `~/forge/.venv/bin/python tap3/live.py --x 5.3 --y 3.85`. If not, `scenario.py` replays a clip and says it is SYNTHETIC.

| t | screen | do | say |
|---|---|---|---|
| 0:00 | Sky Fix :8130 | follow DEMO_90S.md (night synthetic frame, then day CH1) | "Bonus first: an isolated person with no GPS who must not transmit. Phone plus sky gives a position with an honest ring." |
| 1:00 | AIR :8150/air | Helene scene; zoom into the peninsula; point at the scale-check line and the red boxes; click **▶ map forming** | "Zoom to Earth. This is real NOAA imagery from Hurricane Helene, 10 cm per pixel. A person is about 5 pixels here, so the detector's boxes are cars, kayaks and debris. That's why nothing reaches fusion from this layer. The drone forms its own map as it flies: 77 real photos, stitched frame by frame, no learned model, no invented pixels." |
| 2:00 | map :8143 | base → **live stitch**; **▶ drone replay** (×30) | "On the search grid the same flight forms the base layer. Each photo runs through an aerial search-and-rescue person detector, and every box becomes a probability field. Most are playground equipment, and we say so. The pink pins are HERIDAL true positives at simulated positions." |
| 3:00 | terminal | `~/forge/.venv/bin/python scenario.py --speed 4 --no-tap` (or without `--no-tap` if there is no mic) | "LAND. The dog goes in: a rover with IMU, ultrasonic and sound sensors, tracked from an overhead phone." |
| 3:05 | dog :8141 | Play ×4: cells shade, pins drop; orange banner = map scale | "Blue is searched; the coverage is subtracted. Pins are stops, spins, knocks." (Say SYNTHETIC if real runs haven't landed.) Optional: `zoom/run.sh` prints a bark-replay command; barks are found at AUC 0.99 on expert labels and enter at low weight. |
| 3:50 | table + fusion :8140 | **tap three, pause, tap three** (or the scenario replay) → C-contact jumps; operator id → **Confirm** | "Someone trapped can tap. A human confirms; the same pin is re-sent as friendly, a-f-G, schema-validated, with my name. Never hostile." |
| 5:00 | map :8143 | **→ lake**, **▶ sonar replay** (or show `:8150/water`) | "WATER. A sonar mosaic forms along the boat's track. The frames are real forward-looking sonar from UATD and the track is a real AUV track, moved onto this lake: simulated placement, on screen. The detector, trained here on UATD, finds the human-body class at 0.91 AP on held-out data. Each red circle is a call-out and becomes a field over water cells only." |
| 6:15 | map :8143 | **COP layers** card: tick *show* for AIR, WATER, Dog; untick *HERIDAL victim pins* and watch the COP change | "One picture: persona prior times clues, plus every sensor's field, labelled by source, each capped so no sensor dominates. Simulated sources can be switched off live." |
| 7:00 | map | **Next best action**: after the sonar, "drone to R379C261, ETA 14 min (team 131 min)" → **Accept** | "It suggests where to look next: the highest-probability cell nobody has searched, and who gets there first. It's a hint and never tasks anything." |
| 7:40 | fusion :8140 | the chain line `nba_decision accept <operator>` and the `b-m-p-w` waypoint (✔ XSD) | "My Accept is in the hash chain with my name, with a waypoint for ATAK." |
| 8:20 | fusion | AAR panel; optionally `curl :8140/verify` | "Time to first contact, time to confirm, area covered, probability captured, all recomputed from the chain. Edit one line and verification fails at that line." |
| 9:10 | map (optional) | **🌀 NOAA disaster layer** inset | "Air, land and water on one map, and a human on every decision." |

**If something breaks:** `./stop_all.sh && ./run_all.sh --keep` keeps the chain, and `bash ~/forge/zoom/run.sh` restarts :8150. Every screen reloads from server state. The screenshots in `screenshots/` and `~/forge/zoom/screenshots/` are the fallback.

**Numbers you can say** (all re-runnable; see `~/forge/zoom/README.md` and the RESULTS files):
- UATD human body AP50 **0.91** on held-out Test_2 (mAP50 0.82).
- Aerial person detector, deployed model (YOLO26l, 0.60 gate) on held-out HERIDAL photos: **AP50 0.23, P 0.55, R 0.23**; YOLO26n AP50 0.30. The **published human baseline** (human observers, not a model) is P 0.59 / R 0.68.
- Barks vs everything else: **AUC 0.99**.
- Stitch: 54/77 photos placed, georeference ±19 m RMS.
- Sonar: 8 of 10 human-body call-outs match a labelled body.
- Night-build numbers: tap3 had 0 confirmed false alarms on real negatives. Perch P(HV) is 0.80–0.89 rotors off vs 0.02–0.04 rotors on. The map prior matches Koester Tables 3 and 7.

**Don't say:**
- that the detector finds people in the NOAA tiles;
- that the sonar or victim-pin positions are real;
- that the hazard captions are reliable (about 2 of 10 were plausible);
- a field hit rate for tap3 or the dog.

Sky Fix shares the story, not the grid: its demo fixes are far from Ohio, so they add no mass here.
