"""
Dog tracker -> glasses bridge.

Reads the dog's lines (serial port, a log file, or stdin), pulls out GPS,
decides where the person should walk, and posts it to server.py so the
glasses arrow points there.

Line formats (match firmware/collar_node/collar_node.ino):
  Heartbeat, once per second:
    HB,DOG1,511,485557,1.9,STILL,<lat>,<lon>,<fix>
    0  1    2   3      4   5     6     7     8
    type,id,seq,millis,activity,state,lat,lon,gps_fix (0 = no fix, 1 = fix)
  Alert, on an event:
    AL,DOG1,512,485600,BARK,<lat>,<lon>,<fix>
    0  1    2   3      4    5     6     7
    type,id,seq,millis,alert_type,lat,lon,gps_fix

Target rule:
  - An AL line whose type is in ALERT_STATES (or an HB whose state is in
    ALERT_STATES, used by the fake log) LOCKS that spot as the target.
  - Otherwise the target is the dog's last good GPS fix.

Usage:
  pip install pyserial            # only needed for --port
  python3 dog_bridge.py --port /dev/tty.usbmodem1101    # 9600 baud, matches firmware
  python3 dog_bridge.py --file dog_log.txt          # replay a saved log
  cat dog_log.txt | python3 dog_bridge.py           # stdin
  (make a fake log for indoor demos: python3 make_fake_dog.py)
"""
import argparse
import json
import sys
import time
import urllib.request

FIELDS = {"type": 0, "id": 1, "seq": 2, "millis": 3, "motion": 4,
          "state": 5, "lat": 6, "lon": 7, "fix": 8}            # HB lines
AL_FIELDS = {"type": 0, "id": 1, "seq": 2, "millis": 3,
             "state": 4, "lat": 5, "lon": 6, "fix": 7}          # AL lines
# Firmware alert types: STILL, TILT, BARK, BUTTON. FOUND is used by the fake log.
# STILL fires every time the dog stops, so it is left out; add it back if wanted.
ALERT_STATES = {"FOUND", "BARK", "BUTTON", "TILT"}


def parse(line):
    p = [x.strip() for x in line.strip().split(",")]
    if not p or p[0] not in ("HB", "AL"):
        return None                       # skip READY and other noise
    F = AL_FIELDS if p[0] == "AL" else FIELDS
    if len(p) <= F["lon"]:
        return None
    get = lambda k: p[F[k]] if F[k] < len(p) else ""
    try:
        lat, lon = float(get("lat")), float(get("lon"))
        if (lat == 0 and lon == 0) or get("fix") == "0":
            lat = lon = None
    except ValueError:
        lat = lon = None
    return {"id": get("id"), "seq": get("seq"), "state": get("state"), "lat": lat, "lon": lon}


def post(server, payload):
    req = urllib.request.Request(server + "/update", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except Exception as e:
        print("post failed:", e, file=sys.stderr)


def lines_from(args):
    if args.port:
        import serial  # pyserial
        ser = serial.Serial(args.port, args.baud, timeout=1)
        while True:
            raw = ser.readline().decode(errors="ignore")
            if raw:
                yield raw
    elif args.file:
        with open(args.file) as f:
            for raw in f:
                yield raw
                time.sleep(args.replay_delay)
    else:
        for raw in sys.stdin:
            yield raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=9600)   # collar_node uses Serial.begin(9600)
    ap.add_argument("--file")
    ap.add_argument("--replay-delay", type=float, default=0.2)
    ap.add_argument("--server", default="http://localhost:8000")
    args = ap.parse_args()

    locked = None   # alert location, once found
    sent = 0
    for raw in lines_from(args):
        d = parse(raw)
        if not d:
            continue
        is_alert = d["state"].upper() in ALERT_STATES
        has_fix = d["lat"] is not None

        if is_alert and has_fix and locked is None:
            locked = {"lat": d["lat"], "lon": d["lon"]}
            print(f"ALERT locked at {locked}")

        if locked:
            payload = {**locked, "label": f"{d['id']} FOUND", "confidence": 0.9}
        elif has_fix:
            payload = {"lat": d["lat"], "lon": d["lon"],
                       "label": f"{d['id']} last seen", "confidence": 0.6}
        else:
            print(f"seq {d['seq']}: no GPS fix yet ({d['state']})")
            continue

        post(args.server, payload)
        sent += 1
        print(f"seq {d['seq']} -> {payload}")


if __name__ == "__main__":
    main()
