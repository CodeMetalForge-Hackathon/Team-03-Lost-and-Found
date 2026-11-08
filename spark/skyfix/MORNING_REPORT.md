# Sky Fix — morning report (overnight build, 2026-11-08)

**Start:** `bash ~/forge/skyfix/run.sh` → phone app `:8130/`, glasses `:8130/?hud=1`, judges `:8130/demo`, phones with
motion sensors `https://<ip>:8131/` (self-signed). Before the demo: `bash run.sh reset-evidence && bash run.sh`.
Demo script: `DEMO_90S.md` (numbers checked on this build). Pushed to Team-3 `spark/skyfix/` (README, RESULTS, DEMO_90S, screenshots).

## What works (verified tonight)
- **Night star solver.** 60/60 synthetic frames solved, median 55 ms. With the exact gravity vector the fix is
  **0.40 km** median, heading error 0.002°. Real phone photos with no gravity vector give sky orientation only, on
  **126/234** (Pixel 4a 87%). Every solved photo with GPS + time passes the "centre above the horizon at the true
  place" check (103/103).
- **Day skyline solver (CH1, 112 held-out photos).** Median 16.3 km, 33% within 5 km. **1 in 5 photos gets a distinct
  match: median 0.53 km, 83% within 5 km**; the rest say AMBIGUOUS.
- **App.** Phone PWA (Night/Day, LOCK TILT, camera input, demo picker, canvas map with rings, recovery bearing), HUD
  mode, judge gallery with truth shown after solving. Hash-chained evidence log (rescuebase-forge Store reused),
  CoT files that validate against the TAK XSD, nothing transmitted. pytest 14/14, Playwright screenshots with no JS errors.

- **Stretch done:** breadcrumb dead reckoning (simulated only), 10 s HUD video (`screenshots/hud_10s.webm`), Boston/Blue
  Hills terrain loaded. Finding: there's no usable skyline around Boston (horizon relief 3.3° vs 10.2° in the Alps), so
  in Boston it's stars only.

- **Hardening:** an independent code review found 8 issues, all fixed with tests. The important ones: in landscape
  the phone's gravity was 180° off, and the upload clock overrode the photo's EXIF time. pytest 14/14. A 20-minute
  soak ran 2,962 solves with 0 failures, flat memory and a verified chain.
- **State at hand-off:** the service is running from `run.sh` (PIDs in `run/`) with an empty evidence log, ready for
  rehearsal. `bash run.sh stop` stops it. vLLM was not touched.

## What failed / what to say out loud
- **The spec target "median ≤ 20 km with 0.3° tilt" fails: it's 40 km.** That's physics, not code: 1° of tilt ≈ 111 km,
  and the stars only contribute 0.4 km. We show both numbers on every synthetic solve ("perfect tilt 0.55 km",
  realistic 34 km) and draw a 1σ ring plus a dashed 95% ring. The truth is inside the 95% ring 53/60 times.
- **The skyline median of 2–10 km is not met** (16.3 km). Errors are bimodal, so we show the confidence flag.
- **The phone capture path is untested on a real phone and real stars** (it's cloudy, and there's no HTTPS cert trust on
  the phone). Accelerometer axis/sign handling follows the W3C spec, with an automatic flip for iOS, checked only by
  unit test and only in portrait.
- **Terrain is loaded only for the Swiss test region.**

## Decisions for Franco
1. Demo frame: `boston_az150_alt35` has a median tilt draw (34 km error, 0.55 km with perfect tilt). Avoid
   `boston_az030_alt35`, which is a 1-in-60 draw (96 km), unless you want to make the "this is why we draw rings" point.
2. Whether to pitch "1 in 5 day photos → ~0.5 km, the rest honestly flagged" (recommended) or lead with the night story only.

Details: `RESULTS.md` (all numbers + re-run commands), `WORKLOG.md` (timeline), `README.md` (limits).
