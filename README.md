# Lost and Found

**Demo video (Nov 8, 2026):** https://youtu.be/KVSfMxm9zHg

**Pitch deck:** https://docs.google.com/presentation/d/1V7dCDq_V7URew4Vyav7c-2HcQN3OX518ELTH0U9ygr0/edit?usp=sharing

slide：https://docs.google.com/presentation/d/1V7dCDq_V7URew4Vyav7c-2HcQN3OX518ELTH0U9ygr0/edit?slide=id.p15#slide=id.p15
Code Metal Forge 2026, "Operation Lost and Found". This is a search-and-rescue picture for finding a missing person. Every sensor we could build or replay over one weekend (a dog's sensor pack<img width="480" height="270" alt="robot-dog-demo-3-preview" src="https://github.com/user-attachments/assets/681099d0-c8d7-4bad-abf7-9b78e7bdea98" />


https://github.com/user-attachments/assets/44f8e1e4-3cf4-4367-a0ad-724418864595

<img width="360" height="640" alt="robot-dog-demo-2-preview" src="https://github.com/user-attachments/assets/63de61ae-a2dd-47ff-9032-05e655e33470" />
<img width="1179" height="663" alt="robot-dog-search-demo-floor" src="https://github.com/user-attachments/assets/9c24b48d-5987-40d1-8cbf-e311966bbac1" />
<img width="1179" height="1701" alt="robot-dog-closeup-ultrasonic-sensor" src="https://github.com/user-attachments/assets/058ff663-e08f-4b73-877e-ff5d0057f990" />
<img width="360" height="640" alt="robot-dog-demo-2-preview" src="https://github.com/user-attachments/assets/2b82c71f-287e-490f-a353-aa235e176f89" />
<img width="480" height="270" alt="robot-dog-demo-1-preview" src="https://github.com/user-attachments/assets/c9e11379-abf0-4151-8153-ee6e741a4a38" />
, a contact mic for taps, a drone's microphone and camera, sonar, a phone looking at the sky) drops its detections into one shared shell. The shell turns them into probability on a search map and suggests where to look next. **Nothing is confirmed until a human taps Confirm.** That decision goes into a hash chain and out as a Cursor-on-Target pin.

Our rule was *honesty beats polish*. Every screen says what is real, what is replayed and what is simulated, and every number below can be re-run.

## The build

| Dog stand-in, close up | Dog stand-in on a search run |
|---|---|
| ![Dog stand-in close-up: ultrasonic ranger and Seeeduino sensor pack](photos/robot-dog-closeup-ultrasonic-sensor.jpg) | ![Dog stand-in walking the venue floor past target cups](photos/robot-dog-search-demo-floor.jpg) |

### Demo videos

Click a preview to open the full video.

| Search run on open floor | Close-up walk | Live sensor readout |
|---|---|---|
| [![Search run preview](photos/robot-dog-demo-1-preview.gif)](photos/robot-dog-demo-1.mp4) | [![Close-up walk preview](photos/robot-dog-demo-2-preview.gif)](photos/robot-dog-demo-2.mp4) | [![Sensor readout preview](photos/robot-dog-demo-3-preview.gif)](photos/robot-dog-demo-3.mp4) |
| [robot-dog-demo-1.mp4](photos/robot-dog-demo-1.mp4) | [robot-dog-demo-2.mp4](photos/robot-dog-demo-2.mp4) | [robot-dog-demo-3.mp4](photos/robot-dog-demo-3.mp4) |

## What's in the repo

| Path | What it is |
|---|---|
| [`spark/night/`](spark/night/) | **Trace Fusion shell** (the main demo, on the DGX Spark): fusion + evidence chain + CoT (:8140), dog stand-in replay with the **Dog's eye** card (:8141), Perch and Listen (:8142), Persona Search Map + Clue Engine + COP + Next Best Action (:8143). Start with its [README](spark/night/README.md) and [DEMO_FLOW](spark/night/DEMO_FLOW.md). |
| [`spark/night/dogeye/`](spark/night/dogeye/) | Dog's-eye reconstruction: the rover's **real** run 10 telemetry (one forward ultrasonic ranger) rebuilt as legs, a 3D scene and a 4D replay, plus a Qwen3 debrief with a fact check. |
| [`spark/zoom/`](spark/zoom/) | **Zoom to Earth**: AIR (NOAA Hurricane Helene imagery + drone map forming), LAND, WATER (forward-looking sonar call-outs) on the same COP (:8150). |
| [`spark/skyfix/`](spark/skyfix/) | **Sky Fix**: a position fix from a phone photo of the stars (night) or the skyline (day), with an honest confidence ring. Offline, transmits nothing (:8130 / :8131). [`city/`](spark/skyfix/city/) = daytime city mode and 4-shot course mode (:8133). |
| [`arduino/`](arduino/) | Final Seeeduino sensor-pack sketch on the dog stand-in (`dog_sensors/`): ultrasonic ranger, accelerometer, sound, DHT11, thermistor. |
| [`pi_pipeline/`](pi_pipeline/) | Pi → Mac sensor pipeline (serial → SQLite → MQTT → CSV) and the **12 recorded runs** (`data/runs/`: walk1–4, run5–12). |
| [`firmware/`](firmware/), [`glasses/`](glasses/) | The original collar → Meta Ray-Ban Display arrow path (below). |
| [`docs/`](docs/) | Hand-off contracts (e.g. `DOG_HANDOFF.md`). |
| [`photos/`](photos/) | Photos, demo videos and GIF previews of the build (shown in [The build](#the-build) above). |

## The demo (10 minutes, one picture)

| Port | Screen | What the judges see |
|---|---|---|
| 8131 (https) | Sky Fix PWA | Phone + sky gives a fix with a ring; no GPS, nothing transmitted |
| 8133 (https) | Sky Fix City / Course | Daytime skyline fix; 4-shot dead reckoning |
| 8140 | Trace Fusion shell | Contacts, **Confirm** with an operator id, `a-u-G` → `a-f-G` CoT (never hostile), hash chain, AAR |
| 8143 | Search Map / COP | Koester 2020 prior × clues + every sensor's field − searched coverage; drone/sonar replay; Next Best Action (a hint, never a tasking) |
| 8141 | Dog replay + Dog's eye | SYNTHETIC dog run replay; the Dog's eye card shows real run 10 |
| 8142 | Perch and Listen | The same speech with rotors off vs on |
| 8150 | Zoom AIR / WATER | Real NOAA imagery, map forming; sonar mosaic |
| 8160 | **Runs Local** — :8160 | GPU/CPU/RAM, service latencies, model weights on local disk, live no-internet check ([`spark/night/telemetry/`](spark/night/telemetry/)) |

Order and script: [`spark/night/DEMO_FLOW.md`](spark/night/DEMO_FLOW.md). Restart: `night/stop_all.sh`, `night/run_all.sh`, `zoom/run.sh reset`, `skyfix/run.sh`.

## Numbers you can say (all re-runnable)

- **Tap Three:** 0 confirmed false alarms on real negatives (ESC-50 knocks and footsteps, 7.8–12.5 h of geophone walk-bys). There is no field hit rate yet.
- **Perch and Listen:** P(human voice) 0.80–0.89 with rotors off vs 0.02–0.04 with rotors on. A linear probe reaches human-voice F1 0.59 at low throttle in an unseen room.
- **Search map prior:** matches Koester 2020 Table 3 distance quantiles and Table 7 find-location shares exactly. Autistic and TD-child personas are verified; hiker, hunter and dementia are illustrative.
- **Sonar:** UATD human-body AP50 **0.91** on held-out data; 8 of 10 call-outs match a labelled body.
- **Aerial person detector:** HERIDAL AP50 0.23, P 0.55 / R 0.23 at a 0.60 gate. Published human observers: P 0.59 / R 0.68.
- **Barks vs everything else:** AUC 0.99.
- **Drone stitch:** 54 of 77 photos placed, ±19 m RMS.
- **Sky Fix:** night with exact gravity gives 0.40 km; with 0.3° phone tilt, 40 km. The spec's ≤20 km at 0.3° is physically unreachable, and we report it as a fail. Day skyline: median 16.3 km on 112 test photos.
- **Dog run 10 (real):** glass wall reached at 21 s (14 cm, 14.5 cm/s), side wall at 36 s (11 cm, 13.2 cm/s), echo lost at 40 s = open floor. 8 of 9 TILT alerts are gait bob.

## Real vs simulated

- **Real:** dog runs (`pi_pipeline/data/runs/`), NOAA Helene imagery, the Aukerman drone flight, UATD sonar frames, ESC-50 / geophone negatives, DroneAudioSet audio, OSM + DEM for the search grid.
- **Simulated or replayed, and labelled on screen:** the dog replay on :8141 (SYNTHETIC run), sonar placement on the lake, HERIDAL victim pins, tap replays when no mic is attached. The dog's-eye headings come from a room prior, not a measurement.
- **Not claimed:** that the detector finds people in the NOAA tiles, that sonar or pin positions are real, or a field hit rate for Tap Three or the dog.

## Original path: collar → glasses arrow

A collar (`firmware/collar_node/collar_node.ino`: GPS, accelerometer, loudness, button) prints `HB,…` heartbeats and `AL,…` alerts. `glasses/dog_bridge.py` locks the target on the first BARK, BUTTON or TILT alert with a GPS fix. `glasses/server.py` relays it. The Meta Ray-Ban Display web app (`glasses/index.html`) draws an arrow and the distance: it turns green within 20°, shows `SEARCH HERE` under 8 m, and shows `SIGNAL LOST` after 5 s without data.

```bash
cd glasses && ./start.sh                         # fake dog run + Cloudflare quick tunnel; open the URL in the Meta AI app
./start.sh /dev/tty.usbmodem1101                 # real collar on USB serial (pip install pyserial)
```

Data format: `HB,<dog_id>,<seq>,<millis>,<activity>,<MOVING|STILL>,<lat>,<lon>,<fix>` and `AL,<dog_id>,<seq>,<millis>,<STILL|TILT|BARK|BUTTON>,<lat>,<lon>,<fix>`.

## Built this weekend vs. existing

All code here was written during the hackathon. We used these open models: Qwen3-8B, Qwen3-VL, YOLO11/YOLO26, PANNs, AST. Datasets: Koester 2020 *Lost Person Behavior* tables, ESC-50, DroneAudioSet, UATD, HERIDAL, NOAA emergency imagery, OSM, USGS DEM. Tools and libraries: cot-validator XSD, Arduino `Wire`, `pyserial`, FastAPI, Cloudflare quick tunnels, and the Meta Ray-Ban Display web app platform.

## Known limits

- The dog stand-in has one forward ranger and no heading, odometry or GPS indoors, so positions are dead-reckoned from range alone. Its thermistor is a contact sensor, not IR (no body-heat channel).
- Field widths, modality weights and the POD model are hand-set and illustrative.
- On venue Wi-Fi with client isolation, phones can't reach the Spark. Use Tailscale, a hotspot or a travel router.
- Collar GPS is about 5 m, and Cloudflare quick-tunnel URLs change on every restart.
