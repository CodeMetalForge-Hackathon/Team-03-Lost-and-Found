# Perch and Listen — results

All numbers below come from two scripts. `tag.py` (≈10 s) writes `results.json`. `probe.py` (≈3 min plus downloads) writes `probe_results.json`.

## 1. Same clip, rotors on vs off (tag.py)
DroneAudioSet; room1 / drone1 / speaker 1 m / mic-dist 50 cm / mic3_8array-up, 8 channels averaged. On Hugging Face the source level is named in dB (60 / 90); the repo README's "Volume 80pc" sample setting is not a Hub folder, so 60 dB is used, with 90 dB perched for contrast. Windows: the 3 five-second windows of the ground-truth source with the highest PANNs human-vocal score (all from File1). P(HV) = strongest AudioSet human-vocal label.

| window | condition | PANNs P(HV) | AST P(HV) | PANNs top tag |
|---|---|---|---|---|
| File1 @25 s, 60 dB | perched (rotors off) | 0.870 | 0.676 | Speech |
| | in flight, throttle low | 0.030 | 0.016 | Vehicle |
| | in flight, throttle high | 0.034 | 0.023 | Helicopter |
| File1 @0 s, 60 dB | perched | 0.863 | 0.734 | Speech |
| | throttle low | 0.026 | 0.014 | Vehicle |
| | throttle high | 0.025 | 0.032 | Helicopter |
| File1 @32.5 s, 60 dB | perched | 0.801 | 0.726 | Speech |
| | throttle low | 0.021 | 0.031 | Hum |
| | throttle high | 0.038 | 0.031 | Helicopter |
| 90 dB source, perched | (3 windows) | 0.807–0.893 | 0.751–0.934 | Speech |

Three windows from one file is a demonstration, not a statistic. In DroneAudioSet the drone is on a frame, not flying; the rotor noise is real.

## 2. Linear probe on frozen AST embeddings (probe.py)
- **Task:** HV / HNV / NH from drone-with-source audio. 2 s windows, 1 s hop. 60 dB source, mic3_8array-up mean, mic-dist 50 cm, throttle low and high.
- **Labels are teacher labels, not human annotation.** PANNs runs on the *clean ground-truth source* in the same window: HV if P(HV) ≥ 0.5; HNV if P(HNV) ≥ 0.4 and P(HV) < 0.2; NH if both < 0.1. Other windows are dropped. 605 windows per condition: 347 HV, 31 HNV, 227 NH.
- **Split by room and drone:** train = room1/drone1 @1 m + room1/drone2 @1 m + room2/drone1 @3 m (3,630 windows). Test = **room3/drone2 @3 m**, a room never seen in training (1,210 windows).
- **Caveat:** every room played the same six source files, so train and test share source *content*. The split tests generalisation to a new acoustic environment and drone placement, not to new sounds.
- **Baseline:** zero-shot AST (AudioSet head → strongest HV/HNV score ≥ 0.3, else NH) on the same test windows.

| test, room3/drone2 | n | probe F1 HV | HNV | NH | probe macro-F1 | zero-shot AST macro-F1 (HV F1) |
|---|---|---|---|---|---|---|
| throttle low | 605 | **0.592** | 0.059 | 0.359 | 0.337 | 0.182 (0.000) |
| throttle high | 605 | 0.080 | 0.075 | 0.464 | 0.206 | 0.182 (0.000) |
| both | 1210 | 0.412 | 0.071 | 0.421 | 0.301 | 0.182 (0.000) |

What this means: a cheap probe recovers some human-voice signal at low throttle in an unseen room (HV F1 0.59, where zero-shot AST finds none). At high throttle it is near chance. HNV has only 31 test windows per condition and is not learned. This backs the design choice: **listen from a perch or a throttle-down window, not in flight.** It does not show reliable in-flight detection.

## Demo
`serve.py` on :8142 serves `demo.html`. Pick a window, press "Listen in flight", then "Land, cut rotors". Both panels show the stored tags from `tag.py`. Pressing play also re-runs PANNs + AST on the GPU (≈60–400 ms) on the peak-normalised listening clip, and that live score is shown under the stored one.
