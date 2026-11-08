# Team 3 — Operation Lost and Found

**Code Metal Forge Hackathon 2026 · BASE-X Boston · Nov 7–8**

Status check-in, Sat Nov 7, 8:56 PM: ideas locked, build in progress. Code lands in this repo through the night; final push before the Sunday 12:00 cutoff.

## The problem

Find an isolated person when there is no GPS, no cell, and emitting a signal is dangerous. Then get the find to the people who can act on it, with a record of how it was made.

## Who we build for

1. **The isolated person** (aircrew, contested, no GPS). Carries a phone. Must not transmit.
2. **The recovery / search team.** Has radios, drones, dogs. Needs one map that every sensor and every clue updates.

## What we are building

One local box at the command post (NVIDIA DGX Spark, 128 GB, no internet) plus thin clients in the field (phone, display glasses, LoRa radio, drone, dog).

| Piece | What it does | Status |
| --- | --- | --- |
| **Sky fix** | Phone photographs stars (night) or the ridgeline (day), solves position and heading from a pre-loaded catalog and terrain model. Zero emission. | building |
| **Echolocation dog robot** | Quadruped platform with active acoustic sensing sweeps the search area and reports returns consistent with a person. | running |
| **Perch and listen** | Drone lands, cuts rotors, listens for voice, knocks, and tap patterns. In-flight drone audio is unusable (NeurIPS 2025 DroneAudioset: F1 0.26 in flight vs 0.97 clean). | building |
| **Ground ear** | Cheap seismic/contact-mic pucks detect footsteps and taps through the floor. | prototype |
| **Trace fusion + evidence log** | Thermal, acoustic, seismic, and clue inputs become one contact with a confidence, a human confirm, and an append-only, hash-chained record. | running |
| **Clue and coverage map** | Typed clues and dog/team coverage update a lost-person-behavior probability grid; swept areas are subtracted. | building |
| **Delivery** | Red/green and bearing to glasses; pins to ATAK via Cursor-on-Target; 200-byte text over Meshtastic LoRa when everything else is gone. | running |

## Why this is not already a product

Fielded tools do one piece each and most need GPS, cloud, or a $10k radio. None combine no-GPS operation, fully local inference, commodity hardware, ATAK/Meshtastic output, and an audit trail. That combination is the build.

## Stack

- NVIDIA DGX Spark (GB10, aarch64), vLLM, PyTorch, YOLO11, PANNs/AST audio taggers, Whisper, Qwen3
- Tetra3 / Cedar plate solving, DEM skyline matching, OpenDroneMap
- PyTAK (Cursor-on-Target), Meshtastic, ATAK-CIV
- Phone client, Meta display glasses, Raspberry Pi / ESP32 sensor nodes

## Repo layout (filling in through the night)

```
spark/        command-post services: fusion, evidence log, map, serving
field/        phone sky-fix client, glasses HUD, sensor-node firmware
robot/        echolocation dog platform
docs/         persona notes, mentor validation, competitive landscape
demo/         replay data and the Sunday demo script
```

## Team

Team 3. Lead: Franco Plathottathil.

## License

See [LICENSE](LICENSE).
