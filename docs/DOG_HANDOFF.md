# Robot Dog Handoff — what Franco needs from the dog runs

**Team 3 · Code Metal Forge 2026 · for Rachel and Matteo · Sat Nov 7, 9:20 PM**

Paste this whole file into your LLM before you touch the dog. It is the spec for the data I need so I can rebuild the dog's run on the Spark as a 3D map that replays over time, then put a model on top of it.

## 1. The one-sentence goal

Every run of the dog must produce **one folder** with time-stamped sensor logs, a labeled events file, and an overhead video (a fixed phone watching the floor from above — not a camera on the dog), all on the same clock, so I can reconstruct where the dog went, what it sensed at each point, and when.

If I cannot line the sensors up with the video in time, the run is useless. Timing is the whole job.

## 2. What each sensor can and cannot do (so nobody over-claims)

| Sensor on the dog | What it really measures | What we use it for | What it cannot do |
| --- | --- | --- | --- |
| Accelerometer / IMU | The dog's own motion: speed changes, turns, stops, shakes | Dog behavior events: stop, spin, pause, "alert" posture. Gait state (walking / still). | Position. IMU drifts to garbage in seconds. Do not try to get XY from it. |
| Ultrasonic / echo sensor | Distance to the nearest surface in front of it (cm) | Room geometry: walls, boxes, openings. "Echolocation map" of where the dog can go. | Detect a person. A person and a box look the same to it. |
| Sound-level sensor (not a mic) | Loudness, as a number | Spikes: a knock, a shout, a bark, a tap pattern. Trigger only. | Tell human from anything else. No audio classification is possible without a real mic. |

If you can tape a phone (recording audio) or a $10 USB mic to the dog's back, do it. Then I can run human-vs-not audio models. Without a mic, sound is a trigger layer only.

## 3. First thing: answer these (text me, or put in `HARDWARE.md`)

1. What board is on the dog (Arduino / ESP32 / Raspberry Pi / the dog's own controller)?
2. Exact sensor parts (IMU model, ultrasonic model, sound sensor model). A photo of the board is fine.
3. Does the IMU have a gyroscope, or accelerometer only?
4. Is the ultrasonic fixed forward, or on a servo that sweeps? If it sweeps, can you log the servo angle?
5. Where does the data go: SD card on the dog, streamed over Bluetooth to a laptop/phone, or both?
6. Sample rate of each sensor as currently coded.
7. Does the dog have a GPS module at all? (Indoors it won't fix, but I need to know.)
8. Battery life under logging.

**Off-leash reality:** a real SAR dog is released and runs. Bluetooth range is ~10 m. So the log must live **on the dog** (SD card, or a phone riding on the dog), not depend on the laptop staying in range. Bluetooth is for control. If the only logging path today is streaming over BT, say so now; we'll either add an SD card or ride a phone on it.

## 4. The data contract (do not change column names)

One folder per run: `data/dog/run_NN_<short-name>/` containing:

### `sensors.csv` — one row per sample, one clock for everything

```
t_ms,ax,ay,az,gx,gy,gz,us_cm,us_angle_deg,sound,battery_v
```

- `t_ms`: milliseconds since the board booted, monotonic, never resets mid-run. This is the master clock.
- `ax,ay,az`: accelerometer in g (or raw counts — say which in HARDWARE.md and never mix).
- `gx,gy,gz`: gyro in deg/s. Leave blank if there is no gyro, but keep the columns.
- `us_cm`: ultrasonic distance in cm. Use `-1` for no echo / out of range, never 0.
- `us_angle_deg`: servo angle if sweeping, else `0`.
- `sound`: the sound sensor's raw reading.
- `battery_v`: battery voltage (even if only every few seconds; repeat the last value).

Rates: **IMU ≥ 50 Hz, ultrasonic ≥ 10 Hz, sound ≥ 20 Hz.** If the board can only do one loop, log everything at 50 Hz and repeat slow values. Do not change the rate during a run.

### `events.csv` — what a human saw happen

```
t_ms,label,note
```

Labels (use exactly these): `sync_clap`, `run_start`, `run_end`, `dog_stop`, `dog_spin`, `dog_bark`, `dog_alert`, `human_still`, `human_moving`, `human_hidden`, `knock`, `shout`, `tap3`, `obstacle`, `other`.

`t_ms` must be on the **dog's clock**. Easiest: one person watches the live stream (or the phone stopwatch started at the clap) and types labels; we convert at the clap.

### `overhead.mp4` — position ground truth (NOT a camera on the dog)

**Why there is a video at all:** the dog's sensors tell us what it felt and heard, but nothing on the dog can tell us *where it is*. The IMU cannot give position (it drifts to garbage in seconds), and there is no GPS inside the building. So something off the dog has to watch where it goes. That is this camera. The dog carries nothing extra.

**What it is:** a phone on a tripod, or taped high on a wall, looking down at the whole demo floor, 30 fps, landscape, does not move for the whole run. Franco tracks the marker on the dog's back in this video and converts pixels to meters using the floor markers. That track is the backbone every sensor reading gets pinned to.

**Why this isn't a cheat:** in the real version a drone looks down at the search area and does exactly the same job. Same pipeline, lower camera.

- Tape **four markers** on the floor at the corners of the area (bright tape X's). Measure the distances between them with a tape measure and write them in `floor.txt`. That lets me turn pixels into meters.
- Put a **bright marker on the dog's back** (orange tape, a tennis ball, anything high-contrast) so I can track it.
- This is how I get XY indoors. There is no GPS in the building and the IMU can't do it. Do not walk the dog around the block for GPS; it isn't needed.

### `floor.txt` — a sketch

Rough floor plan: where the four markers are, their measured spacing, where the obstacles and the "person" are. A photo of a hand sketch is fine.

## 5. The sync ritual (do this at the start of every run, no exceptions)

1. Start the overhead video.
2. Start the dog logger. Confirm `t_ms` is counting.
3. Hold the dog still. Someone stands next to the dog, in camera view, and **claps hard once, right next to the dog**. That one clap shows up as a spike on the sound sensor, a jolt on the IMU (if you tap the dog at the same time, even better), and a visible frame in the video.
4. Type `sync_clap` in events.csv at that moment.
5. Wait 10 seconds with the dog still (gives me a resting baseline).
6. Type `run_start`, release the dog.
7. At the end: `run_end`, stop logger, stop video.

Without the clap I cannot align the three files. With it, I can align to about 30 ms.

## 6. Runs to collect tonight (in this order; ~45 minutes total)

| Run | What | Why I need it | Length |
| --- | --- | --- | --- |
| 01_still | Dog on the floor, motors off, nobody near | Noise floor for every sensor | 60 s |
| 02_line | Drive straight 5 m, stop 3 s, turn 180°, come back | Tells me what "walking", "stop", "turn" look like on the IMU | 2 min |
| 03_sweep | Drive the dog slowly around the perimeter of the taped area, ultrasonic facing the walls | Echolocation map of the room | 3 min |
| 04_alerts | 10× stop-and-hold, 10× spin, 10× bark (or whatever "alert" the dog can do). Label every one. | Training examples for the alert detector | 5 min |
| 05_sounds | Dog still. 10× knock on a table, 5× shout, 10× tap-three (three taps, ~1 s apart), 1 min of normal room noise. Label every one. | Sound-trigger thresholds; Tap Three detection | 5 min |
| 06_search_A | Free run, 3 min, one person standing still in a corner | The actual search scenario | 3 min |
| 07_search_B | Free run, 3 min, person walks around | Moving target | 3 min |
| 08_search_C | Free run, 3 min, person hidden behind a box, knocks every 20 s | Hidden + sound cue | 3 min |
| 09_demo_dry | The exact run you'd do in front of judges, full ritual | Rehearsal data | 3 min |

Repeat 06–08 once more if you have time. More runs beat longer runs.

## 7. Hand it to me

- Commit each run folder to the team repo: `https://github.com/CodeMetalForge-Hackathon/Team-3` under `data/dog/`. Video over ~100 MB: put it on a USB stick or AirDrop to Franco and note the filename in the folder.
- Message Franco when a run lands with the run name and anything that went wrong (BT dropout, dog fell over, logger restarted). A bad run with notes is useful; a bad run with no notes is noise.

## 8. Don'ts

- Don't change sample rate, units or column names between runs.
- Don't let `t_ms` reset (a reboot mid-run = new run folder).
- Don't skip the clap.
- Don't move the overhead camera once a run starts.
- Don't log to two places with two clocks (e.g., laptop timestamps and board timestamps) without saying which is master. Board clock is master.
- Don't claim the ultrasonic found a person. It found a surface.

## 9. What I build from it (so you know why each piece matters)

1. Overhead video + markers → dog XY track in meters, 30 fps (the 2D).
2. Track + ultrasonic → occupancy map of the room; track + IMU → where the dog stopped/spun; track + sound → where spikes happened (the layers, the 3D).
3. Everything on `t_ms` → scrub-able replay, second by second, with "already searched" area subtracted as the dog covers it (the 4D).
4. Alerts + sound spikes + any thermal/camera input → fused "contact" with a confidence and a human confirm, written to the evidence log on the Spark.
5. Later: a model on the IMU/sound windows to call alerts automatically, trained on runs 04 and 05.

Questions: text Franco. If you're unsure whether something matters, log it anyway and label it `other`.
