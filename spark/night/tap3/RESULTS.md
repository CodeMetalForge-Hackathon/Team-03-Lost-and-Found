# Tap Three — results

Re-run: `~/forge/.venv/bin/python night/tap3/eval.py` (≈40 s) → `eval_results.json`. Every number below is copied from that file (re-run 2026-11-08 00:56, identical to the first run).

## Detector (detect.py)
Spectral-flux onsets (23 ms window, 5 ms hop, threshold = running median + 6·MAD) → a **pattern** is 3 onsets whose gaps are each within ±15 % of their mean gap, mean gap 0.5–1.5 s, peak amplitudes within 6× of each other, and **no other onset louder than −12 dB of the weakest tap** inside 1.5 × gap before the first or after the third tap, or between them. (Guard onsets come from a lower 3·MAD threshold so near-threshold neighbours still veto.) **Confirmed** = a second pattern with a gap within 25 % starting within 10 s of the first.

## Negatives (real recordings, no taps)
| set | duration | patterns | confirmed | confirmed FA/h |
|---|---|---|---|---|
| ESC-50 `door_wood_knock`, 40 clips, also run as one concatenated stream | 0.056 h | 0 | 0 | 0 |
| ESC-50 `footsteps`, 40 clips, also concatenated | 0.056 h | 0 | 0 | 0 |
| footstep_8env geophone, 576 recordings, fs assumed 5000 Hz | 12.46 h | 1 | 0 | 0 |
| same, fs assumed 6500 Hz | 9.59 h | 0 | 0 | 0 |
| same, fs assumed 8000 Hz | 7.79 h | 0 | 0 | 0 |

The `.mat` file carries no sample rate. The step period is ~3500 samples, so the plausible range is 5–8 kHz; all three are reported.
ESC-50 is only 0.11 h, so "0 FA" on it is weak evidence. The geophone set (8–12 h of people walking past) is the meaningful number.

Two earlier detector versions failed here, and the failures are why the design looks like it does: v1 fired 15–20 patterns/h on geophone walk-bys (three loud steps whose quieter neighbours were just under the onset threshold). v2 fixed that but measured "loudness" on log-compressed flux, so background steps 8× quieter still vetoed real taps.

## Sensitivity — SYNTHETIC, not a field hit rate
Synthetic taps (decaying 900 Hz sinusoid + click), two patterns per trial, gap 0.7–1.3 s, ±5 % jitter, added to real ESC-50 background streams. 30 trials per cell. "Ratio" = tap peak / background peak.

| background | 8× (18 dB) | 4× (12 dB) | 2× (6 dB) | 1× |
|---|---|---|---|---|
| footsteps (pattern / confirmed) | 1.00 / 1.00 | 0.57 / 0.23 | 0.27 / 0.07 | 0.13 / 0.00 |
| door knocks | 1.00 / 1.00 | 0.60 / 0.03 | 0.17 / 0.03 | 0.10 / 0.03 |
| rain | 1.00 / 1.00 | 0.83 / 0.23 | 0.10 / 0.00 | 0.10 / 0.00 |

What this means operationally: the detector is built for the call-out/listen protocol (everyone silent, as with a Delsar LD3). Taps must be ~18 dB above whatever else is happening. If people are walking or knocking at a similar level, it stays quiet by design, which is why the false-alarm rate is zero.

## Team recordings (30 pos / 30 neg, 10 s WAVs)
**Not yet received.** When they land in `night/data/tap3/pos/` and `night/data/tap3/neg/` (or with `pos`/`neg` in the filename), re-run `eval.py`. The `team_recordings` block then reports hit rate (pattern and confirmed) and false alarms per hour, and this section gets updated from it.

## Live
`live.py` streams the mic (sounddevice → arecord fallback), or replays a WAV in real time with `--wav`. It prints one JSON line per event (timestamp, interval, confidence, 3 s clip path) and appends to `events.jsonl`; confirmed events go to `night/inbox/` as `tap_pattern_3`. At build time `arecord -l` listed no capture device on the Spark, so live mic use needs a USB mic or contact mic plugged in. The WAV-replay path was tested end to end into the inbox.
