# Dog's-eye reconstruction: run 10, 3D then 4D, from one forward ranger

This takes the dog stand-in's real telemetry from **run 10** (`~/projects/Team-3/pi_pipeline/data/runs/run10_20261108-040115`: 52 heartbeats, 51 s, 13 alerts) and rebuilds what the dog did. The result is a set of legs, a 3D scene, a replay over time (4D) and a debrief written by an open model. The only spatial sensor is **one forward Grove ultrasonic ranger**, so position comes from range alone. **walk1** is the second example. It shows where the method breaks down.

```bash
cd ~/forge/night/dogeye; P=~/forge/.venv/bin/python; R=~/projects/Team-3/pi_pipeline/data/runs
$P reconstruct.py $R/run10_20261108-040115 out/run10 --room-prior   # legs.json, track.csv
$P scene.py  out/run10                                              # scene.ply, scene.glb, topdown.png, dogseye.png
$P fourd.py  out/run10                                              # replay.mp4 (26 s, 30 fps, 2×), replay.html
$P intel.py  out/run10                                              # intel.md (Qwen3-8B debrief + Qwen3-VL reading + fact check)
# optional, NOT installed: $P cop_export.py out/run10 run10_dogeye  (would put run 10 into the map/AAR/scenario)
```
The same pipeline runs on walk1 without `--room-prior`, and with `fourd.py --speed 4` (70 s video).

## Method: sonar dead reckoning
1. **Legs.** The run is split at range discontinuities (|Δd| > 25 cm in one 1 s step, or the echo appearing or disappearing). Each piece between splits is a *heading block*. Inside a block, each 1 s step is labelled down, up or flat (±4 cm deadband; a lone step under 8 cm counts as flat). This gives `approach` (range falling), `retreat` (range rising) and `park` (range flat). A park with mostly MOVING samples is marked "gait active, holding at the surface". Each discontinuity becomes a `turn`. A block with no echo is `open`, split where the debounced STILL/MOVING state changes.
2. **Track.** Within a block, the dog is assumed to keep one heading and to move only along it, toward or away from one fixed surface. Then `x_along = d_min − d(t)` and speed = −dd/dt. Turns happen in place, so the next block's surface sits at `P_end + d_start · h_next`. A sample taken mid-turn (still settling right after a jump) is held at the turn point.
3. **Scene (3D).** Local frame in metres, with the floor at z = 0. Each heading block gets a **sensed surface** patch at its wall point. Patch width = beam footprint at d_min + 20 cm; height 0.6 m. The beam is a 15° cone from the nose at 0.12 m. **Coverage** is the floor area the cone sweeps, in 5 cm cells at 0.1 s steps. Turning intervals get no coverage credit, because the heading is unknown while turning. With no echo the beam is credited 0.9 m, which is where its lower edge meets the floor (0.12 m / tan 7.5°). The ranger's nominal reach is about 3.5 m, so 0.9 m is the conservative choice.
4. **Replay (4D).** The same scene at 1 Hz data, interpolated to 30 fps at 2×. The cone shortens as the dog closes on a wall. Each surface appears once the beam has found it. The coverage raster fills in. TILT, BARK and STILL markers appear on the timeline. The dog marker vibrates in proportion to activity. Strip charts show range, activity, therm_c, temp_c and humidity. A slot is reserved for Franco's phone video; it fills automatically if `night/data/dog/run10/video.mp4` appears (it hasn't yet).

## Two heading solutions, and why neither is measured
The pack has **no heading sensor**. A range jump tells us the dog turned, but not by how much.
- **(a) SENSOR-ONLY**: turns assumed 90°, alternating left and right, in an unanchored frame. This uses nothing beyond the sensor stream, but the 90° is an assumption.
- **(b) ROOM-PRIOR**: run 10 only. Headings come from the corner in Franco's video and photo: left wall, then glass wall (front), then side wall, then open floor, at 180° / 0° / 270° / 90° in a local frame. **This is a prior from the photo, not a measurement.** It is the solution used in the renders, the replay and the COP export, and it is labelled on every one of them.

Both solutions are in `legs.json` (`solutions`) and `track.csv` (`sensor_only_*`, `room_prior_*`). The legs, ranges, speeds and times are identical in both. Only the layout differs.

## Run 10: legs (from `out/run10/legs.json`)
| # | t (s) | kind | d_min–d_max (cm) | speed (cm/s) | events | reading |
|---|---|---|---|---|---|---|
| 0 | 0–5 | park | 7 | | | parked 7 cm from the left wall (HB at 4–5 s already report MOVING, act 6.8/3.6) |
| 1 | 5–7 | turn | 7→72 | | STILL 6.1, TILT 7.3 | range jumps 7 → 55 → 72: heading change |
| 2 | 7–17 | park | 70–74 | | STILL 11.3, TILT 16.9 | facing the glass wall, mostly STILL |
| 3 | 17–21 | approach | 72→14 | 14.5 | TILT 19.9 | 72 → 58 → 43 → 25 → 14 |
| 4 | 21–23 | park | 14–15 | | | at the glass wall; range flat, gait active |
| 5 | 23–26 | retreat | 15→40 | 8.3 | TILT 23.1, **BARK 24.45** | backs off; the loud sound comes 1–3 s after arrival |
| 6 | 26–29 | park | 38–41 | | TILT 27.8 | holds at ~40 cm, gait active |
| 7 | 29–30 | turn | 38→90 | | | range jumps to 90: heading change |
| 8 | 30–36 | approach | 90→11 | 13.2 | TILT 30.9, 33.9 | toward the side wall |
| 9 | 36–38 | park | 11–12 | | TILT 37.5 | at the side wall |
| 10 | 38–39 | retreat | 12→23 | 11 | | backs off |
| 11 | 40–43 | open | no echo | | TILT 40.5 | echo lost = open floor ahead |
| 12 | 44–51 | open | no echo | | | STILL from 44 s |

The brief matches the data except for small details. The first MOVING heartbeats come at 4–5 s, not 6 s. The BARK is at 24.45 s (24.5 in the brief). The retreat ends at 40 cm at 26 s, then holds at 38–41 cm until 29 s. **TILT is gait bob:** 8 of the 9 TILT alerts fall on MOVING heartbeats, at roughly 3 s intervals, which is the board's cooldown. **The BARK** is one loud sound during the back-off right after arrival at the glass wall. It is labelled "loud sound (servos/handler likely)", not "bark".

## Renders and outputs (`out/run10/`)
`topdown.png`, `dogseye.png` (first person from the ranger at 19 s and 33 s), `scene.ply` (7,972 coloured points), `scene.glb` (trimesh, vendored in `dogeye/vendor/`, so the shared venv is untouched), `replay.mp4` (**26.0 s**, 30 fps, 2×), `replay.html` (self-contained and offline, with a time slider), `intel.md`. The same set for walk1 is in `out/walk1/` (replay 70 s at 4×).

## Open model on top (`intel.py`)
vLLM on :8001 and :8002 was down, so both models ran locally with transformers, bf16 and greedy decoding: **Qwen3-8B** (loads in about 85 s, generates in 65 s) for the debrief, and **Qwen3-VL-8B-Instruct** (`~/models/qwen3-vl-8b-instruct`; the HF-cache copy has no weights) for reading the renders. The prompt requires 10 debrief lines that cite times and ranges, plus the three flags. The model's output is kept verbatim. **Below it, `intel.md` adds a fact check computed by code from track.csv, because the model got some of the details wrong.** In flag A it listed 3 TILTs and called the 6.1 s STILL alert a TILT; the data has 8 of 9 TILTs while MOVING. In flag C it said the last range before echo loss was 12 cm; it was 23 cm at 39 s. The VL answer is labelled **"model reading of a rendered reconstruction, not of the room."**

## On :8141, and not in the COP
The **Dog's eye** card on :8141 lists every reconstruction under `dogeye/out/` that has a `legs.json` (today run10 and walk1). It reads them directly from there through `GET /api/dogeye` and `GET /api/dogeye/{name}/{file}`, with file names whitelisted to replay.mp4, intel.md, topdown.png, dogseye.png and replay.html. It does **not** depend on `data/dog/`, so the run selector, the map's dog coverage, `scenario.py` and the AAR all stay on `run_00_synthetic`. The card says so on screen. The changes are confined to that card: two endpoints in `dog/serve.py` and the card in `dog/replay.html`. Backups of the pre-dogeye files: `dogeye/.bak_serve.py`, `dogeye/.bak_replay.html`.

`cop_export.py` is kept but **not installed**. It would write `night/data/dog/run10_dogeye/layers.json` in the processed-run format (coverage = swept cone on the 0.5 m grid, POD illustrative; SIMULATED placement at the start of the planned course; alerts at confidence 0, so scenario.py never emits them). Because real runs are preferred over SYNTHETIC, installing it would switch the map, the AAR and scenario.py (which would then drop no dog pins) to run 10. It was removed at the user's request on Nov 8. Re-add it only deliberately: `$P cop_export.py out/run10 run10_dogeye`; undo with `rm -r ~/forge/night/data/dog/run10_dogeye`.

## Limits
- **Single forward range at 1 Hz.** There is nothing to the sides. Motion is assumed to be along the beam. A sideways drift or a slow turn inside a block looks like a range change. 1 Hz under-samples a 15 cm/s approach (15 cm per sample).
- **No heading and no odometry.** Turn angles are unknown (hence the two solutions). Scale comes only from the ranges to surfaces. In open floor the position simply freezes.
- **Beam width.** ±7.5° means the "surface" is wherever the strongest echo came from inside the cone. A wall at an angle, a chair leg or a person all look the same. A sensed surface is never a person.
- **The thermistor is not IR.** therm_c (14.4–14.7 °C, with THERM_K off) is a contact/ambient reading. It carries no body-heat channel. temp_c and humidity are DHT11 ambient values.
- **walk1 breaks the method.** Only 41 of 281 heartbeats have an echo (handheld, open space). That gives 47 heading blocks and 88 legs, mostly `open`. Sensor-only dead reckoning there is a sequence of unrelated 90° guesses. Its renders are kept as an honest counter-example, not as a map. Its heartbeats span 280 s, while run.json gives 324 s of receiver wall time.

## What more sensors would change
- **A second ranger** (side-facing), **or a 2D lidar**: heading from wall angles, so turns become measured instead of assumed. A lidar alone gives a real scan-matched map.
- **Wheel or leg odometry, or step counting from the IMU with a calibrated stride**: scale and position in open floor, where today the track freezes.
- **A gyro** (the MMA7660 is accelerometer only): turn angles directly, which removes the need for the room prior.
- **An IR thermopile** (e.g. MLX90614/90640): the body-heat channel the story wants. The thermistor cannot provide it.

## Files
`reconstruct.py` · `common.py` (pose, cone, coverage, pinhole renderer) · `scene.py` · `fourd.py` + `replay_template.html` · `intel.py` · `cop_export.py` · `out/{run10,walk1}/` · `screenshots/` · `WORKLOG.md`
