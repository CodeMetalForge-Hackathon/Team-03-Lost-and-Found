# Lost and Found

Code Metal Forge 2026 hackathon project. A search dog wears a sensor collar. When the dog finds someone, the handler's Meta Ray-Ban Display glasses show an arrow pointing to that spot, plus the distance to it.

```
 Dog collar (Arduino)  --serial-->  dog_bridge.py  --HTTP POST-->  server.py  <--poll--  Glasses web app
 GPS, accelerometer,                parses lines,                  /update                index.html
 loudness, button                   locks alert spot               /target                arrow + distance
```

## Repo layout

| Path | What it is |
|---|---|
| `firmware/collar_node/collar_node.ino` | Arduino sketch for the dog's collar. Reads GPS (I2C), accelerometer (I2C), loudness sensor and button. Prints a heartbeat line every second and an alert line on events. |
| `glasses/index.html` | Web app for the Meta Ray-Ban Display (600x600, black = transparent). Draws the direction arrow, distance and turn hints. |
| `glasses/server.py` | Small bridge server. Serves the glasses app and relays the latest target. |
| `glasses/dog_bridge.py` | Reads collar lines (serial, file or stdin), picks the target, posts it to the server. |
| `glasses/make_fake_dog.py` | Generates a fake dog run for indoor demos. |
| `glasses/dog_log.txt` | Sample fake run made with `make_fake_dog.py`. |
| `glasses/start.sh` | One-command demo launcher: server + Cloudflare tunnel + dog data. |
| `arduino/` | Final Seeeduino sensor-pack sketches (`dog_sensors/`, `i2c_scanner/`). |
| `pi_pipeline/` | Pi -> Mac sensor data pipeline (serial -> SQLite -> MQTT -> CSV). See `pi_pipeline/README.md`. |

## Hardware

| Part | Connection |
|---|---|
| Arduino-compatible board | USB serial to laptop, 9600 baud |
| GPS module | I2C, address `0x10` |
| MMA7660-style accelerometer | I2C, address `0x4C` |
| Loudness sensor | `A0` |
| Button module | `D2` |
| Button LED (optional) | `D3` |
| Meta Ray-Ban Display glasses | Opens the web app through the Meta AI app |

Pins and addresses are set at the top of `collar_node.ino`.

## Collar data format

Heartbeat, once per second:

```
HB,<dog_id>,<seq>,<millis>,<activity>,<MOVING|STILL>,<lat>,<lon>,<fix>
```

Alert, when something happens:

```
AL,<dog_id>,<seq>,<millis>,<STILL|TILT|BARK|BUTTON>,<lat>,<lon>,<fix>
```

`fix` is 1 when GPS has a valid fix, 0 otherwise. Alert meanings: `STILL` the dog stopped after moving, `TILT` the dog sat down (about 30 degrees of tilt), `BARK` sound well above the room baseline, `BUTTON` the handler pressed the button.

`dog_bridge.py` locks the target on the first `BARK`, `BUTTON` or `TILT` alert that has a GPS fix. Until then the arrow points to the dog's last known position. Edit `ALERT_STATES` in `dog_bridge.py` to change which alerts count.

## How the arrow works

The glasses app polls `/target` every 500 ms. It accepts any of these:

- `{"relative": 30, "distance": 42}` angle relative to the wearer
- `{"bearing": 75, "distance": 42}` absolute compass bearing
- `{"lat": 42.36, "lon": -71.06}` target position; the app computes bearing and distance from the wearer's position and heading

The arrow turns green within 20 degrees of straight ahead, shows `SEARCH HERE` under 8 m, and goes grey with `SIGNAL LOST` if no data arrives for 5 seconds.

## Run it

Requirements: Python 3, `cloudflared`, and `pyserial` for a real collar (`pip install pyserial`).

```bash
cd glasses
./start.sh                              # demo with the fake dog run
./start.sh /dev/tty.usbmodem1101        # real collar on USB serial
```

`start.sh` prints a public URL. Open it in the Meta AI app as the glasses web app. On the glasses, pinch (or press Enter) once to turn on the compass. Pinch again to switch between LIVE and DEMO. In DEMO mode the D-pad left/right rotates a fake target.

For indoor demos without GPS on the glasses, the URL includes `?me=<lat>,<lon>` to fix the wearer's position.

Flash the collar: open `firmware/collar_node/collar_node.ino` in the Arduino IDE, select the board and port, upload. The serial monitor (9600 baud) should print `READY` and then `HB` lines.

## Built this weekend vs. existing

Everything in this repo was written during the hackathon. External pieces: Arduino `Wire` library, Python standard library, `pyserial`, Cloudflare quick tunnels, and the Meta Ray-Ban Display web app platform.

## Known limits

- GPS is accurate to about 5 m, so the last few meters rely on the dog and the handler.
- Glasses heading comes from the phone/glasses orientation sensor. If only a relative heading is available, the arrow follows head turns but is not north-referenced.
- Cloudflare quick tunnel URLs change on every restart.

## Spark night build: status (Sun Nov 8, ~01:00)

Trace Fusion shell + live sensors, on the DGX Spark. Details: [`spark/night/README.md`](spark/night/README.md), demo order: [`spark/night/DEMO_FLOW.md`](spark/night/DEMO_FLOW.md).

| piece | port | status | headline number (re-runnable) |
|---|---|---|---|
| Fusion inbox → contacts → human confirm → CoT → hash chain → AAR | 8140 | working, 9 tests | CoT validates against the cot-validator XSD; an edited chain record fails `/verify` at that line |
| Tap Three detector (contact mic) | → 8140 | working; **no team recordings yet** | 0 confirmed false alarms on ESC-50 knocks/footsteps + 7.8–12.5 h geophone walk-bys ([results](spark/night/RESULTS_tap3.md)) |
| Dog stand-in ingest + replay | 8141 | working on a **SYNTHETIC** run; real runs re-process with one command | sync 0.4 ms / track 1.6 cm vs synthetic truth ([results](spark/night/RESULTS_dog.md)) |
| Perch and Listen | 8142 | working | P(human voice) 0.80–0.89 rotors off vs 0.02–0.04 rotors on; probe HV F1 0.59 (low throttle, unseen room) ([results](spark/night/RESULTS_perch.md)) |
| Persona Search Map + Clue Engine | 8143 | working | prior matches Koester 2020 Table 3 quantiles and Table 7 find-location shares exactly; hiker/hunter/dementia illustrative |
| Sky Fix (Persona 1 phone) | 8130 | separate session | see [`spark/skyfix/`](spark/skyfix/) |
