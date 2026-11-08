# 10-minute demo flow

**Before judges arrive (2 min):**
1. `cd ~/forge/night && ./stop_all.sh && ./run_all.sh` starts a fresh evidence chain; the old one is archived.
2. Sky Fix: `bash ~/forge/skyfix/run.sh reset-evidence && bash ~/forge/skyfix/run.sh`, following `~/forge/skyfix/DEMO_90S.md`.
3. Open tabs in this order: Sky Fix `:8130`, dog replay `:8141`, fusion console `:8140`, perch `:8142`, map `:8143`.
4. If a USB or contact mic is plugged in, run `~/forge/.venv/bin/python tap3/live.py --x 5.3 --y 3.85` in a terminal and test one tap-three. If not, `scenario.py` replays a clip and says it is SYNTHETIC.
5. Map: persona **Autistic**, layer **posterior**, then press ⌂ IPP.

| t | screen | do | say |
|---|---|---|---|
| 0:00 | Sky Fix :8130 | follow DEMO_90S.md (night synthetic frame, then day CH1) | "Persona 1: an isolated person with no GPS who must not transmit. Phone plus sky gives a position with an honest ring." |
| 1:30 | map :8143 | persona Autistic, rings visible; point at the VERIFIED badge and the class table | "Persona 2: a lost autistic child. This prior is Koester 2020: distance rings from Table 3, and 78 % of the mass in structures from Table 7, fitted together. Switch to Typical child and watch it spread out." |
| 2:30 | map | layer → uncertainty | "Every cell carries its uncertainty from the sample size: 233 subjects vs 903. Hiker, hunter and dementia are marked illustrative." |
| 3:00 | terminal | `~/forge/.venv/bin/python scenario.py --speed 4 --no-tap` (or without `--no-tap` if there is no mic) | "The dog goes in. Tonight it's a rover with an IMU, ultrasonic and sound sensors, tracked from an overhead phone, the way a drone would track a real dog." |
| 3:10 | dog :8141 | Play ×4: cells shade, the track draws, pins drop, ultrasonic outlines the walls | "Blue is where it has searched. Pins are where it stopped, spun, or heard a knock. The grey dots are walls from the ultrasonic. Surfaces, never people." (Say SYNTHETIC if real runs haven't landed.) |
| 4:30 | fusion :8140 | candidates appear (C01–C04, p 0.09–0.49) | "Every dog alert lands here as a candidate contact with a confidence. Nothing is confirmed by a machine." |
| 5:00 | table + fusion | **tap three, pause, tap three** on the table with the contact mic (or let the scenario replay it) | "Someone trapped can't shout, but they can tap. Three even taps, twice." C04 jumps to ~0.91 with tap3:tap_pattern_3 in its sources. |
| 5:40 | fusion | type an operator id → **Confirm** on C04 | "A human confirms. That writes an ATAK pin, validated against the CoT schema, and logs it on the hash chain with my name." Point at the green chain-OK pill and the CoT box. |
| 6:20 | perch :8142 | pick a window → Listen in flight → **Land, cut rotors** | "Why we listen from a perch: same speech, same second. Rotors on, the models hear a helicopter. Rotors off: Speech 0.87. Our probe on an unseen room gets F1 0.59 at low throttle and nothing at high throttle. So we land and listen." |
| 7:20 | map :8143 | zoom to the dog sector (orange box): contacts are pinned, C04 is green, searched cells drop a band | "Back on the one screen: the searched sector is subtracted, the contacts sit on the map, probability re-ranks." |
| 7:50 | map | Add clue → **Witness sighting** 1 h ago, click a spot → Add | "A neighbour saw her an hour ago. The map re-ranks, and the update carries its provenance: hand-set expert prior, not calibrated. That clue is on the evidence chain too." |
| 8:40 | fusion | AAR panel; optionally `curl :8140/verify` | "Time to first contact, time to confirm, area covered, probability captured per hour, all recomputed from the chain. Edit one line of the log and verification fails at that line." |
| 9:20 | — | wrap | "One shell, live sensors, a human on every decision, and an audit trail you can take to a debrief." |

**If something breaks:** `./stop_all.sh && ./run_all.sh --keep` keeps the chain. Every screen reloads from the server state. The screenshots in `screenshots/` are the fallback.

**Numbers you can say** (re-runnable; see the RESULTS files): tap3 0 confirmed false alarms on ESC-50 knocks/footsteps and 7.8–12.5 h of geophone walk-bys; perch P(HV) 0.80–0.89 rotors off vs 0.02–0.04 rotors on; probe HV F1 0.59 low / 0.08 high throttle on an unseen room; the map prior matches Koester Table 3 quantiles and Table 7 shares exactly. **Don't say:** a field hit rate for tap3 (no team recordings yet), or anything about the dog's accuracy on real runs.

Sky Fix results and its 90-second script: `~/forge/skyfix/DEMO_90S.md`, `~/forge/skyfix/RESULTS.md`; in the repo, `spark/skyfix/`.
