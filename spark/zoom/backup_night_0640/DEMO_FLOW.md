# 10-minute demo flow

**Before judges arrive (2 min):**
1. `cd ~/forge/night && ./stop_all.sh && ./run_all.sh` starts a fresh evidence chain; the old one is archived.
2. Sky Fix: `bash ~/forge/skyfix/run.sh reset-evidence && bash ~/forge/skyfix/run.sh`, following `~/forge/skyfix/DEMO_90S.md`.
3. Open tabs in this order: Sky Fix `:8130`, dog replay `:8141`, fusion console `:8140`, perch `:8142`, map `:8143`.
4. If a USB or contact mic is plugged in, run `~/forge/.venv/bin/python tap3/live.py --x 5.3 --y 3.85` in a terminal and test one tap-three. If not, `scenario.py` replays a clip and says it is SYNTHETIC.
5. Map: persona **Autistic**, layer **COP**, press ⌂ IPP and **↺** (drone not flown yet).

| t | screen | do | say |
|---|---|---|---|
| 0:00 | Sky Fix :8130 | follow DEMO_90S.md (night synthetic frame, then day CH1) | "Persona 1: an isolated person with no GPS who must not transmit. Phone plus sky gives a position with an honest ring." |
| 1:20 | map :8143 | persona Autistic; point at the VERIFIED badge and class table; flip layer → uncertainty and back to COP | "Persona 2: a lost autistic child. Koester 2020: distance rings from Table 3, 78 % of the mass in structures from Table 7, fitted together. Every cell carries its uncertainty from the sample size." |
| 2:00 | terminal | `~/forge/.venv/bin/python scenario.py --speed 4 --no-tap` (or without `--no-tap` if there is no mic) | "The dog goes in. Tonight it's a rover with IMU, ultrasonic and sound sensors, tracked from an overhead phone, the way a drone would track a real dog." |
| 2:05 | dog :8141 | Play ×4: cells shade, track draws, pins drop, ultrasonic outlines the walls; orange banner = map scale | "Blue is searched. Pins are stops, spins, knocks. Grey dots are walls from the ultrasonic. Surfaces, never people." (Say SYNTHETIC if real runs haven't landed.) |
| 3:00 | fusion :8140 | candidates appear (C01–C04, p 0.09–0.49) | "Every alert lands as a candidate contact, an *unknown* a-u-G pin. Nothing is confirmed by a machine." |
| 3:20 | table + fusion | **tap three, pause, tap three** on the table (or let the scenario replay it) | "Someone trapped can't shout, but they can tap." C04 jumps to ~0.91 with tap3 in its sources. |
| 3:50 | fusion | operator id → **Confirm** C04 | "A human confirms. The same pin is re-sent as *friendly*, a-f-G, schema-validated and logged with my name. Never hostile." |
| 4:30 | perch :8142 | Listen in flight → **Land, cut rotors** → **send perched detection to fusion** | "Rotors on, the models hear a helicopter. Rotors off: Speech 0.87. We send that to the shell: it becomes a contact at the perch point." |
| 5:20 | map :8143 | **COP layers** card: tick *show* for Tap Three, Perch, Dog; untick one source and watch the COP change | "This is the operating picture: persona prior times clues, plus every sensor's probability field, labelled by source: tap is a tight Gaussian scaled by signal strength, perch a wider one, dog alerts at the dog. Searched ground is subtracted." |
| 6:10 | map | **▶ drone replay**: the Aukerman orthomosaic forms tile by tile under the real flight track; drone coverage drops a band | "This is the real survey flight: 77 photos, 17 minutes, replayed at 30×. The map forms as the drone flies, and what it has seen is subtracted." |
| 7:00 | map or fusion | **Next best action** panel: "Suggest: drone to R…C…, ETA 2 min (team 10 min)" → **Accept** | "The system suggests where to look next: the highest-probability cell nobody has searched, and who gets there first. It's a hint. It never tasks anything by itself." |
| 7:30 | fusion :8140 | point at the chain line `nba_decision accept <operator>` and the `b-m-p-w` waypoint pin (✔ XSD); on the map the blue flag and the next suggestion | "My Accept is in the hash chain with my name, and there's a waypoint pin for ATAK. The next suggestion moves on." |
| 8:00 | map (optional) | Add clue → Witness sighting 1 h ago → the COP and the suggestion re-rank | "A clue arrives and the picture updates, with its provenance on screen." |
| 8:40 | fusion | AAR panel; optionally `curl :8140/verify` | "Time to first contact, time to confirm, area covered, probability captured, all recomputed from the chain. Edit one line and verification fails at that line." |
| 9:20 | — | wrap | "One shell, live sensors, one picture, a human on every decision, and an audit trail you can take to a debrief." |

**If something breaks:** `./stop_all.sh && ./run_all.sh --keep` keeps the chain. Every screen reloads from the server state. The screenshots in `screenshots/` are the fallback.

**Numbers you can say** (re-runnable; see the RESULTS files): tap3 0 confirmed false alarms on ESC-50 knocks/footsteps and 7.8–12.5 h of geophone walk-bys; perch P(HV) 0.80–0.89 rotors off vs 0.02–0.04 rotors on; probe HV F1 0.59 low / 0.08 high throttle on an unseen room; the map prior matches Koester Table 3 quantiles and Table 7 shares exactly. **Don't say:** a field hit rate for tap3 (no team recordings yet), or anything about the dog's accuracy on real runs.

Sky Fix shares the story, not the grid: its demo fixes are in Boston, the Alps and Hawaii with km-scale rings, so none fall on the Ohio search grid. Its CoT files (`~/forge/skyfix/cot/`) use the same XSD-validated format as ours. Sky Fix results and its 90-second script: `~/forge/skyfix/DEMO_90S.md`, `~/forge/skyfix/RESULTS.md`; in the repo, `spark/skyfix/`.
