# Dog stand-in pipeline — results

**No real runs have arrived yet.** Everything below was measured on `data/dog/run_00_synthetic`, which `make_synthetic_run.py --seed 7` generates in the exact DOG_HANDOFF format. That file holds the ground truth, so these numbers check the code, not the rover. Re-run with `dog/process_run.sh data/dog/run_00_synthetic`.

| check | result | what it means |
|---|---|---|
| floor markers | auto-detected (green tape), M1 = nearest image top-left, clockwise | written to `floor_px.json` + `floor_check.png` so a human can verify |
| track vs synthetic truth | median 0.016 m, p95 0.019 m (4500/4500 frames, HSV) | **optimistic:** the synthetic marker sits on the floor plane. A real marker ~15 cm up on the rover adds parallax (several cm, more near the image edge) |
| sync vs hidden clock offset | error 0.4 ms (offset 9151.4 ms vs true 9151) | clap found in the video's audio track + sound sensor + IMU jolt |
| sound vs IMU clap residual | 40 ms | the synthetic IMU jolt is placed 12 ms after the clap; 50 Hz sampling gives the rest |
| typed `sync_clap` − sensor clap | +257 ms | human typing lag, which is why the typed label is reported but not used |
| knocks found as sound spikes | 5 / 5 | needed a rolling 5 s median/MAD: a global threshold missed 2 of 5 because the motor raises the floor while moving |
| ultrasonic hits vs true walls/boxes | median 0.046 m, p90 0.082 m from the nearest true surface | needed 0.3 s track smoothing before taking the heading; unsmoothed, hits landed up to 1.8 m outside the walls |
| coverage | 23.5 m² with POD ≥ 0.5 (0.5 m cells) | POD model 1 − e^(−dwell/1.5 s) with 0.75 m sweep radius is **illustrative**, not a measured dog POD |

Bugs found and fixed while building: the tracker locked onto a brown box that falls inside the orange HSV range (fixed by masking blobs that are static across the video); the generator looped forever when drift made the rover miss a waypoint.

When a real run lands: `dog/process_run.sh data/dog/run_NN_name` (add `--clap-frame N` if the video has no audio). The replay at :8141 lists real runs before synthetic ones, and the map and AAR use the newest real run automatically.
