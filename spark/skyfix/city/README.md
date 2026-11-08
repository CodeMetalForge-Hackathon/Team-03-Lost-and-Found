# Sky Fix · City (daytime) mode

Position, height and heading from **one photo of a city skyline**: no GPS, no compass. The user taps 3 known landmarks;
three-point resection (Snellius–Pothenot) gives the position, the sea horizon gives the height, and the floor follows.

**How it runs today:** the **phone is the camera, the Spark is the solver**, over **local Wi-Fi, with no internet**.
The phone opens `https://<spark>:8133/` (or taps **🏙 CITY (daytime)** in the Sky Fix PWA on :8131, which links there), takes a photo, uploads it to the Spark and shows the result. Everything the solver needs
at run time is in the **pre-mission pack** (`city/pack/`, **0.55 MB**: landmarks 0.07 MB, building footprints with heights
0.48 MB). That pack is what would ship on the phone for on-device solving. **No raster map tiles are in it:** the OSM tile server
answered all 313 requests with its "Access blocked" placeholder image. The first run cached those images as if they were tiles,
which I caught when rendering. They were deleted (one sample is kept as `data/osm_tile_403_blocked_sample.png`), and the maps
now draw the pack's OSM footprints as vectors. A licensed tile source, or self-rendered tiles, would be needed for a raster
base. The solver is ~300 lines of numpy and has not been ported to the phone tonight. The only optional network call is the
USGS ground-elevation lookup, which is cached and falls back to 5 m.

```bash
cd ~/forge/skyfix/city
~/forge/.venv/bin/python build_pack.py            # landmarks + building footprints (Overpass) + tiles; run once with internet
~/forge/.venv/bin/python app.py 8133 --https      # phones: https://<spark-ip>:8133/ (accept the self-signed cert)
~/forge/.venv/bin/python -m pytest -q tests       # synthetic geometry tests
~/forge/.venv/bin/python eval_truth.py            # ground truth on the two Boston photos (needs results/taps_*.json)
~/forge/.venv/bin/python course.py && ~/forge/.venv/bin/python course_png.py   # course mode -> results/course.json, course.png
```

## The math

**Lens.** The focal length in pixels comes from EXIF `FocalLengthIn35mmFilm`: `f_px = f35 / 36 mm × long side px`. If that
tag is missing it uses `FocalLength` mm divided by a sensor width from `config.json`, and failing both a **69° HFOV** iPhone
main lens. The 36 mm long-side convention matches the 69° figure. The diagonal convention would give ~67° for a 4:3 frame,
which is a 3% scale error in every angle; see Limits.

**Attitude.** Two taps on the sea horizon give the roll. The horizon sits below true horizontal by the dip,
`dip = √(2h(1−k)/R)` with refraction k = 0.13. The pitch is solved per horizon tap so that the tap's elevation equals −dip,
then averaged. A line of constant elevation projects as a curve under pitch, so the midpoint of the two taps is not on it.
The dip depends on the unknown height h, so h and the pitch are iterated (it converges in 2–3 rounds). Without horizon
taps the camera is assumed level and no height is computed; the UI says so.

**Bearings.** Each tapped pixel (u right, v up, roll removed) has camera ray `(u, v, f)`. Rotating it by the pitch gives
`azimuth offset φ = atan2(u, f cos p − v sin p)` and a true elevation `e`. The heading is unknown, but differences of φ are
exact angles between landmarks: `α = φ_B − φ_A` and `β = φ_C − φ_B`.

**Resection (Snellius–Pothenot), closed form.** Chord AB subtends angle α only from points on a circle through A and B.
Its centre sits at the chord midpoint plus the normal times `|AB| / (2 tan α)`; there are two candidates, one per side.
The same holds for BC with β. Both circles pass through B, so the camera P is **B reflected across the line joining the
two centres**. The four centre combinations are scored on the directed angles they reproduce, and the exact one is kept.
A Gauss–Newton polish on (E, N, heading) then minimises the bearing residuals; it also accepts more than 3 landmarks.
The solution is singular when P lies on the circle through A, B and C (the "danger circle"). The distance to that circle
is reported, with a warning below 15% of its radius.

**Confidence ring.** α and β are each perturbed by −0.5°, 0 and +0.5° (9 combinations) and re-solved. The ring is the
largest displacement. 0.5° is about 25 px at f ≈ 2900 px, which is roughly how well a person taps a rooftop.

**Heading and sun check.** `heading = bearing(P → landmark) − φ`, averaged over the landmarks. astropy gives the sun's
azimuth and altitude at the EXIF time (EXIF offset, or −05:00 assumed) at the solved position. The page says where the sun
should be relative to the view: in frame at pixel x (a dashed line), or N° left or right. That is a check on the heading, and
on the left-right order of the taps, independent of the landmarks.

**Height and floor.** For a landmark tapped at its top, with known top height above sea level (ground from USGS 3DEP plus the
building height): `h_cam = top_asl − d · tan(e_top) − d²(1−k)/2R`. Here d is the solved distance; the curvature term is
about 1 cm at 400 m. The height above street is `h_cam − ground(P)`, and `floor = height above street / (ft per floor)`.
ft per floor is a visible parameter, 13.7 for 60 State St.

**Expected skyline overlay (sanity check, not in the solver).** OSM footprints with heights (1,484 in the pack) are rendered
from the fix and the eye height into a 360° elevation-vs-azimuth profile at 0.25° bins. That profile is projected into the
photo with the solved camera, as the green line. If the fix is right, it hugs the real rooftops.

## Landmarks (`data/landmarks.json`, cited; `pack/landmarks.json`, 259 items)
| landmark | lat, lon (OSM footprint centre) | top height | source |
|---|---|---|---|
| Custom House Tower | 42.359045, −71.053567 (way 29719177) | 151.2 m (496 ft) | Wikipedia roof; OSM 151 |
| Harbor Towers I | 42.358119, −71.049806 (way 240415950) | 121.9 m (400 ft) | Wikipedia; OSM 121 |
| Harbor Towers II | 42.357670, −71.050489 (way 240415949) | 120.7 m (396 ft) | Wikipedia; OSM 120 |
| One International Place | 42.355706, −71.052150 (way 241176918) | 182.9 m (600 ft) | Wikipedia roof; OSM 183 |
| Millennium Tower | 42.355705, −71.059507 (way 95035761) | 208.5 m (684 ft) | Wikipedia roof; OSM 209 |
| State Street Bank Bldg (225 Franklin) | 42.356134, −71.053938 (way 139980427) | 145.4 m (477 ft) | Wikipedia roof; OSM 145.39 |
| Faneuil Hall cupola | 42.36001, −71.05608 (east end of way 29551702) | ~29 m, **unverified** | hand value; Wikipedia gives no height |
| Zakim Bridge S / N tower | 42.368014, −71.062275 / 42.369575, −71.064057 (ways 485005954/963) | 82.3 m (270 ft) | Wikipedia. OSM tags 98 m; that tag was judged wrong and is not used (noted in landmarks.json) |
| Bunker Hill Monument | 42.376352, −71.060767 (way 212124093) | 67.4 m (221 ft) | Wikipedia; OSM 67; ground 24 m |
Ground elevations come from USGS 3DEP 1 m (EPQS). Positions: © OpenStreetMap contributors (ODbL). Heights: English Wikipedia
(CC BY-SA), fetched 2026-11-08; raw wikitext is in `data/wiki_*.txt`.

## Ground truth
**Pending.** `boston.jpg` and `boston2.jpg` never arrived in `city/` during the session, so the single-shot ground truth against 60 State St (14th floor, 58 m) has **not been run**. `eval_truth.py` is ready. The course-mode run below uses four different photos from the same windows and is scored against the same truth.

## Course mode: 4-shot dead reckoning on 60 State St (`course.py`, `:8133/course`)

**Input:** four iPhone 18 Pro originals (IMG_1196–1199 → `shots/01..04_*.heic`, kept local), 08:21:32 → 08:23:36 (124 s).
**Metadata:** EXIF has **no GPS tags and no GPSImgDirection**. No compass and no GPS are used: the **clock**
(DateTimeOriginal) and the **lens** (FocalLengthIn35mmFormat 24 → f = 3950 px, 56.9° portrait HFOV) are the only metadata used
(`results/course_exif.json`). Only EXIF-stripped 1200 px JPEG copies are in the repo (`shots_web/`), because the frames show
the venue and people's reflections.

**Method.**
- Bearings: φ = atan((px − cx)/f), level camera assumed. (E, N, heading) is fitted by grid search plus Gauss–Newton over ≥ 3
  observations per shot. Observations are point landmarks plus building-silhouette edges (the left or right footprint vertex as
  seen from the current camera, or a named corner).
- **Glazing gate:** the camera is snapped onto the 60 State outline (`pack/buildings.json`, h = 155) on the face segment whose
  outward normal is within ±35° of the heading. The heading is then re-fitted with that position fixed.
- **Height:**
  - (a) shot 01: Custom House tip against the sea horizon (y 0.414), with dip 0.0293°·√h, iterated twice;
  - (b) every known-height landmark on its own;
  - (c) shots without a horizon: pitch and h fitted jointly over that shot's known-height landmarks.
  - Joint h = median of the per-shot values that converged. A (c) fit with |pitch| > 15° or RMS > 1° counts as not converged;
    that rule was fixed before scoring.
- floor = round((h − 6)/3.85) + 1.
- The truth (`results/course_truth.json`) is used only for scoring.

| shot | time | post-gate fix | heading | face | gate moved | bearing RMS |
|---|---|---|---|---|---|---|
| 01 | 08:21:32 | 42.35934, -71.05615 | 76.7° | E | 10.6 m | 0.49° |
| 02 | 08:22:21 | 42.35909, -71.05632 | 164.8° | S | 46.8 m | 11.07° |
| 03 | 08:22:54 | 42.35913, -71.05671 | 246.3° | W | 115.1 m | 13.02° |
| 04 | 08:23:36 | 42.35950, -71.05657 | 344.2° | N | 24.3 m | 1.01° |

Legs: 01→02 31.3 m straight (~46.9 m corridor) in 49 s = 0.96 m/s; 02→03 32.5 m straight (~48.8 m corridor) in 33 s = 1.48 m/s; 03→04 42.9 m straight (~64.3 m corridor) in 42 s = 1.53 m/s. Loop **clockwise** (signed area -1284.1 m²); faces **E-S-W-N**.

**Score** against the stated truth (60 State St, 14th floor, camera 53–58 m above street; headings 073/170/232/344°; position
error is measured to the midpoint of the true face's longest OSM segment):

| shot | face solved / true | position error pre → post gate (m) | heading error | shot height |
|---|---|---|---|---|
| 01 | E / E | 22.7 → **16.9** | +3.7° | 48.1 m |
| 02 | S / S | 48.5 → **12.5** | -5.2° | 63.0 m |
| 03 | W / W | 117.6 → **14.8** | +14.3° | 137.9 m (did not converge, excluded) |
| 04 | N / N | 42.8 → **28.4** | +0.2° | 62.8 m |

- **Joint h 62.8 m** (median of shots 01, 02 and 04): h error **4.8 m** against the 53–58 m band
  (**+4.8 m** against 58 m).
- **Floor 16: wrong** (truth 14).
- **Direction: right** (clockwise), and **faces: right** (E, S, W, N).
- Every single-landmark height estimate, so the bad ones are visible: 01 Custom House Tower tip 48.1 m [(a)] · 01 Marketplace Center glass gable tip 32.4 m [(b)] · 01 Harbor Towers I roof 52.8 m [(b)] · 02 One Federal St roof 43.6 m [(b)] · 02 1891 Stock Exchange balustrade 58.5 m [(b)] · 03 Ames Building roof cornice 49.4 m [(b)] · 03 Old State House east gable 42.3 m [(b)] · 03 Boston Massacre circle 30.7 m [(b)] · 04 Hub on Causeway / Verizon roof 36.1 m [(b)] · 04 Bunker Hill Monument tip 12.1 m [(b)] · 04 Holocaust Memorial glass tower 56.5 m [(b)].
  The level-camera (b) values spread from 12 to 59 m. Phone pitch dominates them.
- Shot 01's sea-horizon height (48.1 m) is 5 m under the band; the joint-fit shots 02 and 04 (63 m) are 5 m over it.
- **Did not converge:** shot 03's pitch+h fit (pitch −40°, h 138 m, RMS 1.5°). Its three height landmarks are all close
  (54–115 m) and the Ames coordinates are hand-entered, so it is excluded from the joint height.
- Shot 03's pre-gate fix was 115 m off. The gate rescued it onto the W face, but its heading error is still 14°.
- Boston Massacre circle check: the ray through the tapped circle (level camera, joint h) lands 61.4 m from
  the pack node (-9.5 m north, -60.7 m east). That does **not** support the "10–15 m north"
  hypothesis. Shot 03's pitch is unknown, and an unknown pitch makes a near-vertical ray unreliable, so this check is inconclusive.

**Course-mode limits.**
- **Single-building assumption:** the glazing gate presumes the photographer is inside 60 State. Without it, the
  least-squares fixes are 23–118 m off.
- Reference heights from OSM and Wikipedia are ±5 m. The Ames Building (60 m, seed coordinates; its OSM footprint centre is 44 m
  away), Marketplace Center (~40 m; the 200 State St address node, ±20 m) and the 1891 Stock Exchange balustrade (~50 m) are
  **hand-entered**. One Federal and Hub on Causeway use seed coordinates.
- Landmark positions are footprint centres, not the exact roof point tapped. At 60–250 m range, a 10 m offset is 2–10° of bearing.
- Level camera for the bearings. No roll correction (no horizon in shots 02–04). One Congress was not used, because which roof
  edge was tapped is ambiguous.
- The taps are the seed hints, accepted as given in headless mode. No human re-tapped them on the frames tonight.
- **No compass used.**

### Evidence
The Course tab's "Log" button appends one hash-chained Sky Fix evidence record per fix (`solver=city_course`, with a CoT file;
all 4 pass the XSD check) plus one `city_course_summary` record. A headless test run wrote SKYFIX-1…5; the chain verifies OK.

## Limits (single-shot mode)
- **Taps are the measurement.** A 0.5° error is about 25 px, and the ring shows what that costs. Tapping the wrong part of a
  building (the top of a tower vs its centreline) adds a bearing error of up to the building's half-width over its distance.
- **The lens scale is a systematic error.** A wrong HFOV scales α and β together. The 36 mm vs diagonal 35-mm conventions
  differ by 3%. The page has an HFOV override, so you can see how much the fix moves.
- **Pinhole only.** No lens-distortion model; iPhone JPEGs are distortion-corrected in-camera for the main lens.
- **Height needs a real sea horizon** and a landmark with a trusted height. For the Zakim towers, 82 m from Wikipedia is used;
  the OSM 98 m tag was judged wrong. The Faneuil cupola height is unverified. A 1 m error in the landmark height is a 1 m error in camera height.
- **Geometry.** Three landmarks bunched in a narrow wedge, or a camera near their circle, give a large ring; the page warns.
- **VLM proposals** (Qwen3-VL-4B, ~50 s to load, running on the Spark) are suggestions only. The user confirms or moves every one.
- The building base elevation in the skyline render is a flat 4 m; buildings without an OSM height use levels × 3.5 m.
