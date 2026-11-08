# pi_pipeline: dog sensor pack -> base station

```
Seeeduino --USB serial--> bridge.py (Pi) --MQTT QoS 1--> Mosquitto (Mac) --> receiver.py (Mac)
                          SQLite bridge.db                                   data/heartbeats.csv
                          (store, then forward)                              data/alerts.csv
```

## Folders

| Path | What it is |
|---|---|
| `arduino/dog_sensors/` | Final Seeeduino sketch. Prints `HB` (1/s) and `AL` lines at 9600 baud. Don't change it. |
| `arduino/i2c_scanner/` | Utility sketch: lists I2C addresses (for checking wiring). |
| `pi_pipeline/bridge.py` | Pi: serial -> SQLite -> MQTT, with store-and-forward. |
| `pi_pipeline/receiver.py` | Mac: subscribes to `dogs/#`, writes CSV, live terminal view. |
| `pi_pipeline/mosquitto.conf` | Mac broker config (port 1883 on all interfaces, no auth, persistence on). |
| `pi_pipeline/dog-bridge.service` | Optional systemd unit to start the bridge at boot. |

## How it works

- **bridge.py** reads serial lines and adds the Pi's wall-clock time (`ts`, ISO 8601). It saves
  every line to SQLite with `sent=0`. A background thread publishes unsent rows in order to
  `dogs/<dog_id>/hb` or `dogs/<dog_id>/alert` and marks each one `sent=1` once the broker acks it.
  If the broker is unreachable, rows pile up and go out on reconnect. If the USB cable is pulled,
  it retries the port every 2 s. `READY`, `WARN,...` and malformed lines are logged and skipped.
- **receiver.py** keeps a persistent MQTT session. If the receiver or broker restarts, the broker
  holds messages for it. HB and AL share one `seq` counter, so gaps are checked across both.
  A drop in seq is reported as a board restart, not a gap.
- `ts` is when the Pi read the line; `received_at` (CSV only) is when the Mac got it. After an
  outage they differ by the outage length. That's expected: `ts` is the real reading time.

## Setup (once)

Pi: `sudo apt install -y python3-serial python3-paho-mqtt mosquitto-clients`
(Pi OS blocks system pip.) Works with paho-mqtt 1.x and 2.x.

Mac:
```
brew install mosquitto
cd pi_pipeline && python3 -m venv .venv && .venv/bin/pip install paho-mqtt
```

## Run (demo)

Current link: **Tailscale**. Mac = `100.71.249.68`, Pi = `100.94.186.8` (`ssh pi`).
The venue Wi-Fi (BASE-X Guest) blocks device-to-device traffic, so the Wi-Fi IPs don't work.
To switch to a phone hotspot later, change only `--broker` to the Mac's hotspot IP
(`ipconfig getifaddr en0`).

1. Broker (Mac, in `pi_pipeline/`):
   ```
   mkdir -p mosquitto_data && mosquitto -c mosquitto.conf -v
   ```
2. Receiver (Mac, in `pi_pipeline/`, second terminal):
   ```
   .venv/bin/python receiver.py
   ```
3. Bridge (Pi, in `~/Team-3/pi_pipeline/`):
   ```
   python3 bridge.py --broker 100.71.249.68
   # options: --port auto|/dev/ttyUSB0  --baud 9600  --db bridge.db
   # no hardware: add --simulate (fake HB + occasional BARK/TILT)
   ```
   To start it at boot instead, see the comments in `dog-bridge.service`.

**Run only one receiver at a time.** It uses a fixed MQTT client id (`dog-receiver`) so the
broker can hold messages for it. A second copy with the same id kicks the first one off,
and each ends up with about half the messages. Check with `pgrep -fl receiver.py`.

## Checking for lost data

```
# Pi: rows stored / rows still unsent
python3 -c "import sqlite3; print(sqlite3.connect('bridge.db').execute('select count(*), sum(sent=0) from readings').fetchone())"
# Mac: rows received (minus 1 header line per file)
wc -l data/*.csv
```
