# Sky Fix — results (every number re-runnable)

Re-run all: `bash results/rerun_all.sh` (≈7 min with cached terrain grids; the grids themselves take ≈10 min).
Raw per-item outputs are in `results/*.json`. Machine: DGX Spark (GB10), CPU for the solvers, GPU only for SAM 2 inference.

## 1. Night — star solver

### 1a. Synthetic sky, 60 frames (`python eval_stars.py` → `results/stars_synth_summary.json`)
10 sites (incl. Boston 42.36,−71.06 and Swiss Alps 46.5,8.0) × headings 30/150/270° × camera altitude 35/60°, HFOV 70°,
2000×1500 px, local solar midnight, seeded handheld roll σ 6°. Rendered from Hipparcos with proper motion, refraction,
airmass extinction, sky glow, Poisson + read noise and 3% random star dropouts (`synth/render_sky.py`).

| | value |
|---|---|
| plate-solve rate | **60/60 (100%)**, all with the phone-FOV database on the full frame |
| solve time (centroids + solve) | median **55 ms**, max 1.12 s |
| matched stars / residual | median 26 stars, 0.0073° RMS |

Position error vs. tilt-sensor error. Gravity vector perturbed by N(0, σ) on each of its two tilt axes; 3 seeded draws
per frame for σ > 0. "1σ ring" = spec formula 111 km × (centroid_rms + 0.3°). "95% ring" uses 2.45 × 0.3°.

| tilt σ per axis | n | median km | p75 km | p95 km | ≤ 20 km | in 1σ ring | in 95% ring | median heading err |
|---|---|---|---|---|---|---|---|---|
| 0 (exact gravity) | 60 | **0.40** | 0.51 | 0.71 | 100% | 100% | 100% | 0.002° |
| 0.1° | 180 | 13.9 | 19.2 | 26.7 | 79% | 99% | 100% | 0.09° |
| **0.3° (braced phone)** | 180 | **40.1** | 55.5 | 82.2 | **15%** | 39% | **95%** | 0.26° |
| 1.4° (handheld) | 180 | 194 | 277 | 380 | 1% | (1σ ring is for braced) | | 1.19° |

**Acceptance:** solve rate ≥ 90% → **PASS (100%)**. Median ≤ 20 km at 0.3° tilt noise → **FAIL (40 km)**, and no
solver can pass it. 0.3° of zenith-direction error is 33 km by the spec's own 111 km/° rule, and with two tilt
axes the median error magnitude is 1.18σ = 0.36°, i.e. 40 km. The stars contribute ~0.4 km. The tilt sensor is the
whole error budget. Refraction-aware refinement brings the exact-gravity median from 2.0 km (first pass, RA−GAST
formula) to 0.40 km.

### 1b. Real night photos (no gravity vector → sky orientation only) (`python eval_real.py`)
No position is ever computed from these photos. The photo's own GPS and time are used afterwards to sanity-check
the solve, never as solver input.

| set | photos | sky solved | solved FOV within 3% of EXIF FOV | solved centre above horizon at true place/time |
|---|---|---|---|---|
| Pixel 4a (high-res, EXIF time) | 67 | **58 (87%)** | 52/58 | 53/53 with GPS |
| Pixel 6 | 24 | 9 (38%) | 9/9 | (no GPS) |
| Pixel 8a | 42 | 23 (55%) | 15/23 | 23/23 |
| Pixel 8 Pro | 64 | 27 (42%) | 20/27 | 27/27 |
| Wikimedia geotagged (mostly panoramas / fisheyes; 7 files re-fetched after the downloader saved HTML error pages) | 37 | 9 (24%) | 0/3 (solved FOV consistently ~10% narrower than EXIF, likely crops; tetra3 false-match prob ≤ 1e-11) | (dates only) |
| **all** | 234 | **126 (54%)** | | **103/103** |

Median time per photo 0.3–0.8 s. Pixel 6 and Wikimedia photos have no usable GPS + UTC offset pair for the
horizon check. EXIF has time, and the horizon is predicted to be inside the frame, for 35 of the 103 checked photos
(those could in principle give a horizon-based tilt; not implemented). Two generic fixes raised the rate from 59 to
123 (126 after re-fetching the 7 broken Wikimedia files). (1) The FOV prior was wrong: EXIF 35 mm-equivalent focal length refers to the 43.3 mm diagonal, and these images
are portrait. (2) An upper-half-only star fallback, chosen on Pixel 4a/6 failures; on the held-out phones Pixel 8a
went 11→23. Before/after summaries: `results/stars_real_summary_v1_badfov.json`, `_v2_fovfix.json`.

## 2. Day — skyline solver, CH1 (Baatz et al. 2012) (`bash results/run_skyline_test.sh`)
Split by location, seeded: 142 locations → **30 DEV** (all method choices) / **112 TEST** (reported). One image per
location. Each location gets a "last known fix" prior 5–15 km from the truth in a random direction (median prior error
9.7 km on TEST); the search box is ±25 km around the prior, so the truth is never at the grid centre. The persona
knows the last fix to tens of km, which is what makes a constrained search honest. Horizon by SAM 2 (median column
error 2.3 px vs. the shipped GT masks; the masks are used only for scoring and for the oracle rows).

| TEST, 112 photos | median km | p75 km | ≤ 5 km | ≤ 2 km | better than prior |
|---|---|---|---|---|---|
| spec baseline: 1 km grid, SAM horizon, detrended RMS | 17.4 | 26.0 | 25.9% | 21.4% | 36% |
| 1 km grid, Pearson correlation (spec "score = correlation") | 17.7 | 26.0 | 18.8% | 14.3% | |
| **deployed: 0.5 km grid, SAM horizon, detrended RMS** | **15.7** | **22.4** | **32.1%** | **29.5%** | 39% |
| 0.5 km grid, oracle GT horizon (upper bound for the horizon step) | 16.3 | 23.1 | 38.4% | 34.8% | |

**Confidence (ratio test).** Margin = best score − best score of any cell > 3 km away, divided by the best RMS.
The threshold of 0.15 was chosen on DEV.

| deployed config | flagged distinct | median km (distinct) | distinct ≤ 5 km | truth inside displayed ring |
|---|---|---|---|---|
| TEST | **23/112 (20.5%)** | **0.53** | **83%** | 19/23 (ring = max(core, 5 km)) |
| DEV | 6/30 (20%) | 2.1 | 67% | 4/6 |

**Acceptance (≥ 20 images, median & p75, fraction ≤ 5 km):** done on 112. The expected median of 2–10 km is
**not met** over all photos (15.7 km). Errors are bimodal: about 30% of photos land within 2 km and most of the rest
are confidently matched somewhere else in the box. The ratio test finds about 1 in 5 photos where the match is
distinct, and those are right to ~0.5 km median. Everything else is shown as **AMBIGUOUS** with the full ring.
The spec ring (radius holding the top-5% of scores) is ~46 km and contains the truth 100% of the time, which makes
it honest but uninformative. Method choices made on DEV only: SAM mask union (2.39 vs 2.93 px), detrended RMS, 0.5 km grid,
margin 0.15. The 5 km ring floor was set after seeing that the core ring alone held the truth only 33% (DEV) and
61% (TEST) of the time. 5 km is the spec's own metric.

Timing (deployed): SAM horizon 75 ms (GPU), matching 0.94 s for 10,201 cells × 360 headings, grid 3–5 s when not
cached (16 processes); cached grid for the demo photos.

## 3. Evidence and CoT
`pytest`: 9 passed. Covers tamper detection (editing record 2 → `verify` reports broken at 2), XSD validation of
our CoT (valid) and rejection of a malformed event, API errors (404/400/422), the gravity conversion, and a planted
skyline match. The CoT is valid against `cot-validator/.../Marker - 2525.xsd`. Nothing is transmitted.

## 4. What would make it metre-class (or at least 1 km-class)
- **Tilt is everything at night.** 0.4 km with exact gravity vs 40 km with a 0.3° braced phone. Paths:
  (a) average the accelerometer over the whole exposure, braced on a rock or rifle rest;
  (b) **reversal**: shoot two frames with the phone rolled 180° about the lens axis and average them, so
  accelerometer bias perpendicular to the lens cancels (standard surveying practice; not yet implemented);
  (c) per-phone accelerometer calibration (six-position) before the mission;
  (d) use a **sea or flat horizon** in the frame as the level reference (35 of our real photos have one in frame);
  (e) a gyro-stabilised exposure and a known lens model (distortion) for sub-arcminute star residuals.
  Star residuals are already 0.007°, i.e. 0.8 km, so with 0.01° tilt the fix would be ~1–2 km. Metre-class from
  a single star fix is not physically available (1 arc-second ≈ 31 m). Metre-class needs multi-frame, multi-hour
  averaging or a different sensor.
- **Day.** Wider horizons (a 3-photo panorama instead of one ~55° frame), finer grid near the top candidates
  (250 m near the truth beat the global 1 km best in 17/30 DEV images), observer height, and a camera roll estimate
  from the phone's gravity vector (which we have on a live phone but not in CH1).

## 5. Stretch: second terrain area (Boston / Blue Hills)
Six GLO-30 tiles (N41–42, W071–073), 0.5 km grid ±25 km around Great Blue Hill, cached (3.6 s with 16 processes).
From the summit (191 m in the 2″ DSM) the maximum horizon elevation is **−0.1°**. Grid median per-cell horizon relief
is **3.3°** vs **10.2°** for a Swiss test location, and it comes mostly from DSM trees and buildings at close range.
No ground-truth day photos exist for Boston, so no accuracy is claimed. We expect skyline matching to be unreliable there.
Re-run: `python -c "import solver_skyline as S; S.grid(42.2120,-71.1143,'blue_hills')"`.
