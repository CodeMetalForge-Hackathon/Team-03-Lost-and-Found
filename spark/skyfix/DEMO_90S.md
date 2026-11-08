# Sky Fix — 90-second demo (exact clicks)

**Before the demo:** `bash ~/forge/skyfix/run.sh reset-evidence && bash ~/forge/skyfix/run.sh`. Open three tabs:
phone app `http://<spark>:8130/` (or on the phone), glasses `http://<spark>:8130/?hud=1`, and `http://<spark>:8130/demo` as backup.
Do one warm-up click (any synthetic frame) so SAM and the databases are loaded (about 5 s the first time), then reset again.

| t | do | say |
|---|---|---|
| 0:00 | Phone app, **★ NIGHT** selected | "No GPS, can't transmit. All you have is the phone and the sky." |
| 0:08 | Picker → **[synthetic] boston az150 alt35** → **USE THIS PHOTO** | "Synthetic sky over Boston with exact truth, because it's cloudy and we're indoors." |
| 0:15 | Result appears (~0.6 s) | "25 stars matched. Big yellow text: bearing **199° S, 20.5 km** to the primary recovery point, Hanscom." |
| 0:25 | Point at the map: yellow ring, dashed ring, green X | "Error **33.9 km**, just inside the 34.5 km ring. With perfect tilt it's **0.55 km**. The stars aren't the limit, the phone's tilt sensor is. 1° of tilt is 111 km, and we draw the ring that way instead of faking a pin." |
| 0:40 | Glasses tab: arrow + distance updated | "The glasses show only the arrow, distance and ring." |
| 0:48 | **⛰ DAY** → picker **[ch1] CH1 _dsc0022_01024** → **USE THIS PHOTO** (cached grid, ~1 s) | "By day: a real Swiss mountain photo. SAM finds the skyline, and we search ±25 km around the last fix against a terrain model." |
| 1:00 | Result | "Distinct match: **0.7 km** from truth, ring ±5 km. The last known fix was 6 km off. When the skyline is ambiguous, it says AMBIGUOUS rather than guessing." |
| 1:12 | Scroll to **Evidence log** / the grey hash line | "Every fix is hash-chained and written as a Cursor-on-Target file, XSD-validated. Transmitted: no. It hands over to ATAK when it's safe." |
| 1:25 | (optional) open `/demo` | "Every photo here has a known location, so you can click any of them and see the error." |

Numbers above were checked on this build (`results/demo_synth_table.json`; the CH1 item is the first TEST-split photo).

**Why this frame:** each synthetic frame gets a deterministic simulated tilt error. `boston_az150_alt35` draws 0.31°,
close to the median of 0.33° across all 60, so it is representative. `boston_az030_alt35` draws 0.86° (about 1 in 60),
which puts the truth at 96 km, outside both rings. If a judge picks it, that's the honest answer: "a bad tilt reading,
and that's why we draw the ring". Across all 60 frames the truth is inside the 1σ ring 27 times and inside the dashed
95% ring 53 times.

**If something fails:** the gallery at `/demo` has the same items with Solve buttons. If the server is down,
run `bash ~/forge/skyfix/run.sh` (about 10 s). Screenshots are in `screenshots/`.

**Live phone (only if there's time and real stars):** open `https://<spark>:8131/` and accept the certificate.
NIGHT → LOCK TILT while aiming → TAKE PHOTO (night mode) at the same tilt. This has not been tested on a real phone
under real stars. Indoors you'll get "no plate solution".
