#!/usr/bin/env python3
"""Pi bridge: Seeeduino serial -> SQLite (store) -> MQTT (forward).

Main thread : read serial, parse, timestamp, INSERT into SQLite (sent=0).
Sender thread: when MQTT is connected, publish unsent rows in order (QoS 1),
               mark each row sent once the broker acknowledges it.
The network can be down for as long as it likes; serial reading never waits on it.
"""
import argparse, datetime, glob, json, logging, random, sqlite3, threading, time

import serial
import paho.mqtt.client as mqtt

HB_FIELDS = ["dog_id", "seq", "t_ms", "activity", "state", "lat", "lon", "fix",
             "temp_c", "humidity", "therm_c", "dist_cm"]
AL_FIELDS = ["dog_id", "seq", "t_ms", "alert", "lat", "lon", "fix"]
INTS = {"seq", "t_ms", "fix", "humidity", "dist_cm"}
FLOATS = {"activity", "lat", "lon", "temp_c", "therm_c"}

log = logging.getLogger("bridge")


def parse(line):
    """Return (kind, dict) for a valid HB/AL line, or None. kind is 'hb' or 'alert'."""
    parts = line.split(",")
    if parts[0] == "HB" and len(parts) == 13:
        kind, names = "hb", HB_FIELDS
    elif parts[0] == "AL" and len(parts) == 8:
        kind, names = "alert", AL_FIELDS
    else:
        return None
    msg = {}
    for name, val in zip(names, parts[1:]):
        val = val.strip()
        if val == "":
            msg[name] = None            # empty field (no GPS, no echo, ...)
        elif name in INTS:
            msg[name] = int(float(val))  # raises ValueError if garbage
        elif name in FLOATS:
            msg[name] = float(val)
        else:
            msg[name] = val
    if not msg["dog_id"] or msg["seq"] is None:
        return None
    return kind, msg


def open_db(path):
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT, dog_id TEXT, seq INTEGER, ts TEXT,
        payload TEXT, sent INTEGER DEFAULT 0)""")
    db.commit()
    return db


def make_mqtt_client(client_id):
    # paho-mqtt 2.x requires a callback API version; 1.x doesn't have the argument.
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    return mqtt.Client(client_id=client_id)


def sender(db_path, client, stop):
    """Forward unsent rows, oldest first. Stops at the first failure and retries later."""
    db = open_db(db_path)
    was_connected = False
    while not stop.is_set():
        connected = client.is_connected()
        if connected != was_connected:
            log.info("MQTT %s", "connected" if connected else "disconnected")
            was_connected = connected
        if not connected:
            time.sleep(1)
            continue
        rows = db.execute("SELECT id, kind, dog_id, payload FROM readings "
                          "WHERE sent=0 ORDER BY id LIMIT 200").fetchall()
        if not rows:
            time.sleep(0.2)
            continue
        if len(rows) > 5:
            log.info("forwarding backlog: %d+ rows", len(rows))
        for row_id, kind, dog_id, payload in rows:
            info = client.publish(f"dogs/{dog_id}/{kind}", payload, qos=1)
            try:
                info.wait_for_publish(timeout=5)
            except (RuntimeError, ValueError):  # not queued (connection dropped)
                pass
            if not info.is_published():
                log.warning("publish of row %d not acked; will retry", row_id)
                break
            db.execute("UPDATE readings SET sent=1 WHERE id=?", (row_id,))
            db.commit()


def find_port(port):
    if port != "auto":
        return port
    ports = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    return ports[0] if ports else None


def serial_loop(args, db):
    while True:
        port = find_port(args.port)
        if not port:
            log.warning("no serial port found; retrying in 2 s")
            time.sleep(2)
            continue
        try:
            with serial.Serial(port, args.baud, timeout=2) as ser:
                log.info("serial open: %s @ %d", port, args.baud)
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue  # timeout, no data
                    handle_line(raw.decode("ascii", errors="replace").strip(), db)
        except (serial.SerialException, OSError) as e:
            log.warning("serial error on %s: %s; reconnecting in 2 s", port, e)
            time.sleep(2)


def simulate_loop(args, db):
    """Fake Seeeduino output (1 HB/s, occasional BARK/TILT), to demo without hardware."""
    seq, start = 0, time.time()
    log.info("SIMULATING serial data as %s", args.dog_id)
    while True:
        t_ms = int((time.time() - start) * 1000)
        handle_line(f"HB,{args.dog_id},{seq},{t_ms},{random.uniform(0, 3):.1f},STILL,,,0,"
                    f"{23 + random.uniform(-0.5, 0.5):.1f},{random.randint(45, 55)},"
                    f"{24 + random.uniform(-0.5, 0.5):.1f},{random.randint(100, 300)}", db)
        seq += 1
        if random.random() < 0.1:
            handle_line(f"AL,{args.dog_id},{seq},{t_ms},{random.choice(['BARK', 'TILT'])},,,0", db)
            seq += 1
        time.sleep(1)


def handle_line(line, db):
    if not line or line == "READY" or line.startswith("WARN"):
        if line:
            log.info("board: %s", line)
        return
    try:
        parsed = parse(line)
    except ValueError:
        parsed = None
    if parsed is None:
        log.warning("malformed line ignored: %r", line)
        return
    kind, msg = parsed
    msg["ts"] = datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")
    db.execute("INSERT INTO readings (kind, dog_id, seq, ts, payload) VALUES (?,?,?,?,?)",
               (kind, msg["dog_id"], msg["seq"], msg["ts"], json.dumps(msg)))
    db.commit()
    if kind == "alert":
        log.info("ALERT %s seq=%d", msg["alert"], msg["seq"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker", default="10.1.200.220", help="broker IP (the Mac)")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--port", default="auto", help="serial port, or 'auto' (ttyUSB*, then ttyACM*)")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--db", default="bridge.db", help="SQLite file")
    ap.add_argument("--simulate", action="store_true", help="fake sensor data, no Seeeduino needed")
    ap.add_argument("--dog-id", default="DOG1", help="dog id used by --simulate")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db = open_db(args.db)
    client = make_mqtt_client("")  # broker picks a unique id, so two bridges never clash
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.connect_async(args.broker, args.mqtt_port, keepalive=10)
    client.loop_start()  # background thread; connects and reconnects on its own

    stop = threading.Event()
    threading.Thread(target=sender, args=(args.db, client, stop), daemon=True).start()
    log.info("bridge started; broker %s:%d, db %s", args.broker, args.mqtt_port, args.db)
    try:
        (simulate_loop if args.simulate else serial_loop)(args, db)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        client.loop_stop()


if __name__ == "__main__":
    main()
