# Forge night build — Trace Fusion shell and its live sensors

Code Metal Forge 2026, "Operation Lost and Found". This folder holds everything the pitch needs apart from Sky Fix (`~/forge/skyfix`, built in parallel, Persona 1 phone module, port 8130).

**Trace Fusion is the shell.** Every sensor drops a JSON detection into `inbox/`. The fuser clusters detections into contacts with a confidence. Nothing is confirmed until a human taps Confirm, and then a Cursor-on-Target pin is written. Every step is appended to a SHA-256 hash chain, and the after-action review is computed from that chain. The live sensors are Tap Three (contact mic), Perch and Listen (acoustic tagger), and the dog stand-in (a rover carrying IMU + ultrasonic + sound-level sensors, tracked by an overhead phone camera). Thermal YOLO from pass 1 writes the same detection format. The **Persona Search Map + Clue Engine** is the one screen the search runs against.

## Run it
```bash
cd ~/forge/night
./run_all.sh            # archives the previous evidence (never deletes), starts 4 services, prints URLs
~/forge/.venv/bin/python scenario.py          # demo driver: dog replay → inbox, then a tap3 replay
./stop_all.sh           # stops only the PIDs run_all.sh started
~/forge/.venv/bin/python -m pytest -q tests   # 9 tests, ~8 s, HTTP-level
```
| port | screen |
|---|---|
| 8140 | fusion console: contacts, Confirm/Clear, evidence chain, CoT, AAR |
| 8141 | dog stand-in replay (scrub, coverage, alerts, ultrasonic, synced video) |
| 8142 | Perch and Listen (rotors on vs off, tags live on GPU) |
| 8143 | Persona Search Map + Clue Engine |

Python: `~/forge/.venv/bin/python`. Two extra packages live in `night/vendor/` so the shared venv is untouched: `imageio-ffmpeg` (ffmpeg binary, used for the clap in the video audio) and `osmium` (OSM extract). The screens make no external requests: no map tiles, no CDNs.

## The pieces

**Tap Three (`tap3/`).** Spectral-flux onsets. A *pattern* is 3 taps at a constant 0.5–1.5 s interval (each gap within ±15 %), with nothing louder than −12 dB of the weakest tap in a 1.5-gap guard window. Two patterns make a *confirmed* event, which goes to the inbox. On real negatives (ESC-50 knocks and footsteps, plus 7.8–12.5 h of geophone walk-bys) it produced **0 confirmed false alarms**. Synthetic taps over real backgrounds are confirmed 100 % of the time at 18 dB above the background, and much less often at 12 dB. It is built for the call-out/listen protocol, not for a noisy room. `live.py` takes a mic or replays a WAV and saves a 3 s clip per event. **Limits:** the team's 30+30 tap recordings have not arrived, so there is no field hit rate yet. No capture device was attached to the Spark tonight. Details: `tap3/RESULTS.md`.

**Dog stand-in (`dog/`).** Implements the DOG_HANDOFF contract. `track_overhead.py` maps the overhead video to metres (homography from four tape markers, HSV marker tracking, background-subtraction fallback). `sync.py` aligns the board clock and the video using the clap, found in the video's audio, the sound sensor and the IMU. `layers.py` produces coverage (0.5 m cells), alerts (stop/spin/sound spike plus labelled events) and an ultrasonic occupancy map. `replay.html` (:8141) is the scrubbable timeline. **Limits:** only a SYNTHETIC run exists so far, and it is labelled on every screen. On it, tracking is within 1.6 cm and sync within 0.4 ms of truth, which is optimistic (no marker parallax, no lighting changes). The POD model is illustrative. Ultrasonic hits are surfaces, never people. Details: `dog/RESULTS.md`.

**Perch and Listen (`perch/`).** One DroneAudioSet configuration (60 dB, room1, drone1, speaker 1 m, mic3 array). The same 5 s of speech with rotors off scores P(human voice) 0.80–0.89 (PANNs) / 0.68–0.93 (AST). With rotors on it scores 0.02–0.04, and the top tag becomes Helicopter or Hum. A linear probe on frozen AST embeddings, tested on an unseen room, reaches human-voice F1 0.59 at throttle low and 0.08 at throttle high (zero-shot AST: 0.00). **Limits:** the probe uses teacher labels (PANNs on the clean source), the rooms share source content, and the drone is on a frame. Details: `perch/RESULTS.md`.

**Fusion + evidence (`fusion/`).** Detections in floor metres or lat/lon are put into one local frame. Clustering radius is 2 m on the floor / 25 m geo. Confidence is noisy-OR over (sensor, kind) pairs, using the spec's modality weights. `POST /confirm` requires an operator id. The chain line is `hash = sha256(prev + canonical record)`; `/verify` re-walks the chain, and an edited record breaks it at that line (tested). A restart rebuilds state from the chain. Every contact is emitted as CoT XML validated against the cot-validator XSD (`Marker - 2525.xsd`). An **unconfirmed contact is `a-u-G`** (unknown ground). When a human confirms it, the **same uid is re-sent as `a-f-G`** (friendly ground), so ATAK updates the pin in place instead of adding a second one. **`a-h-*` (hostile) is never used: a survivor is not hostile.** `fuse.py` refuses any `a-h` type at start-up and at write time, and a test checks this. Files: `evidence/cot/NIGHT-Cxx.xml` (current) plus `.candidate.xml` / `.confirmed.xml`. Every pin write is chained with its type, XSD result and sha256. Sample pins are in `sample_pins/` in the repo copy. `aar.py` reports time to first contact, time to confirm, area covered and probability captured (and per hour).

**Persona Search Map + Clue Engine (`map/`).** A 20 × 20 km grid of 50 m cells around the LKP, built from OSM (roads, trails, water, 35k buildings) and the 1-arc-second DEM. The prior is fitted by iterative proportional fitting so that **both** Koester 2020 marginals hold exactly: distance quantiles (Table 3) and find-location shares (Table 7). Example: 78 % of ASD mass sits in structure cells and 50 % inside 0.9 km. Uncertainty comes from 40 Monte Carlo draws whose spread follows each persona's sample size. The Clue Engine has 8 clue types; posterior ∝ prior × LR(cell) × (1 − POD of searched areas). Searched-area POD uses Koester 2020 sweep widths (64 m day / 22 m night) with the exponential coverage model. Each clue shows its provenance, and positive-clue LRs are labelled hand-set expert priors. Clue and persona changes go onto the fusion chain. Dog coverage subtracts at a **labelled demo scale: 1 dog floor cell (0.5 m) = 1 map cell (50 m)**, i.e. ×100, so the 7 × 5 m floor (taped area plus margin) stands in for a 700 × 500 m sector. The label is on the replay page and on the map. Optional Qwen3-VL clue-type proposals degrade gracefully when :8002 is down. **Limits:** autistic and TD-child personas are verified; hiker, hunter and dementia are ILLUSTRATIVE. Table 7 says ASD subjects are found near water *less* often than TD children (5 % vs 8 %), so the map does not boost water for ASD even though the master prompt suggested it (review decision, Nov 8: keep the data-driven weighting and the on-screen note). Because distance and terrain class are fitted as independent marginals, the 3 structure cells inside 400 m (the park shelter) hold 18 % of the mass.

## Background watcher
`watch_data.py` (started by hand at 00:59; `./stop_all.sh` stops it) polls every 30 s. When a real dog run folder appears in `night/data/dog/` (or in `~/projects/Team-3/data/dog/`, symlinked in, read-only), it runs `dog/process_run.sh` on it. When new WAVs land in `night/data/tap3/`, it re-runs `tap3/eval.py`. Results and failures are logged to `WORKLOG.md`. Restart it with `( cd ~/forge/night && exec nohup ~/forge/.venv/bin/python watch_data.py > logs/watch.log 2>&1 ) &`.

## Honest gaps at hand-off
- No real dog runs and no real tap recordings yet. Both pipelines re-run with one command when they land (copy or symlink run folders into `night/data/dog/`, taps into `night/data/tap3/{pos,neg}/`).
- vLLM on :8001/:8002 was down all night. It was not restarted, because the GPU is shared with the Sky Fix session. Clue proposals then say so and the operator picks the type.
- The geophone sample rate is not in the dataset file, so false-alarm rates are reported at three plausible rates.

---
*Repo copy:* `code/` mirrors `~/forge/night` on the Spark, without data, vendor packages, logs or evidence. Run it from `~/forge/night`, where datasets and models are in place. Screenshots are in `screenshots/`; raw result JSON sits next to the RESULTS files; `sample_pins/` holds one contact's CoT before (a-u-G) and after (a-f-G) human confirm.
