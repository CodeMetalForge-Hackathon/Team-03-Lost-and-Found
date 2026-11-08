#!/usr/bin/env python3
"""Mac receiver: subscribe to dogs/#, append to CSV, show a live view, detect seq gaps.

Uses a persistent MQTT session (fixed client id, clean_session=False, QoS 1), so if the
receiver or the broker restarts, the broker holds messages for it instead of dropping them.
"""
import argparse, collections, csv, datetime, json, os, time

import paho.mqtt.client as mqtt

HB_COLS = ["received_at", "ts", "dog_id", "seq", "t_ms", "activity", "state", "lat", "lon",
           "fix", "temp_c", "humidity", "therm_c", "dist_cm"]
AL_COLS = ["received_at", "ts", "dog_id", "seq", "t_ms", "alert", "lat", "lon", "fix"]


class Receiver:
    def __init__(self, outdir):
        os.makedirs(outdir, exist_ok=True)
        self.writers = {}
        for kind, cols, name in (("hb", HB_COLS, "heartbeats.csv"), ("alert", AL_COLS, "alerts.csv")):
            path = os.path.join(outdir, name)
            new = not os.path.exists(path) or os.path.getsize(path) == 0
            f = open(path, "a", newline="")
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            self.writers[kind] = (f, w)
        self.latest = {}                      # dog_id -> last HB dict
        self.last_seq = {}                    # dog_id -> last seq seen (HB and AL share it)
        self.alerts = collections.deque(maxlen=8)
        self.events = collections.deque(maxlen=8)   # gaps / restarts / duplicates
        self.arrivals = collections.deque()  # arrival times, for the rate
        self.counts = collections.Counter()
        self.gaps = 0
        self.connected = False

    def on_message(self, topic, payload):
        try:
            msg = json.loads(payload)
            kind = topic.split("/")[-1]
            dog = msg["dog_id"]
            seq = int(msg["seq"])
        except (ValueError, KeyError, TypeError):
            self.events.append(f"bad message on {topic}: {payload[:60]!r}")
            return
        if kind not in self.writers:
            return
        now = time.time()
        msg["received_at"] = datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")
        f, w = self.writers[kind]
        w.writerow(msg)
        f.flush()
        self.counts[kind] += 1
        self.arrivals.append(now)
        self.check_seq(dog, seq)
        if kind == "hb":
            self.latest[dog] = msg
        else:
            self.alerts.append(f"{msg['ts'][11:23]}  {dog}  {msg['alert']}  (seq {seq})")

    def check_seq(self, dog, seq):
        last = self.last_seq.get(dog)
        if last is not None:
            if seq == last + 1:
                pass
            elif seq > last + 1:
                self.gaps += seq - last - 1
                self.events.append(f"GAP {dog}: seq {last} -> {seq} ({seq - last - 1} missing)")
            elif seq <= last and last - seq < 5:
                self.events.append(f"duplicate/out-of-order {dog}: seq {seq} after {last}")
                return  # keep last_seq
            else:
                self.events.append(f"{dog} seq reset {last} -> {seq} (board restarted?)")
        self.last_seq[dog] = seq

    def draw(self):
        now = time.time()
        while self.arrivals and now - self.arrivals[0] > 10:
            self.arrivals.popleft()
        out = ["\033[H\033[J",  # clear screen
               f"broker {'CONNECTED' if self.connected else 'DISCONNECTED'}   "
               f"rate {len(self.arrivals) / 10:.1f} msg/s (10 s)   "
               f"total hb={self.counts['hb']} alerts={self.counts['alert']}   seq gaps={self.gaps}", ""]
        for dog, m in sorted(self.latest.items()):
            age = now - datetime.datetime.fromisoformat(m["ts"]).timestamp()
            out.append(f"[{dog}] seq {m['seq']}  taken {m['ts'][11:19]} ({age:.0f} s ago)")
            out.append(f"  state {m['state']}  activity {m['activity']}  temp {m['temp_c']} C  "
                       f"humidity {m['humidity']} %  therm {m['therm_c']} C  dist {m['dist_cm']} cm")
            out.append(f"  gps fix {m['fix']}  lat {m['lat']}  lon {m['lon']}")
        out += ["", "Recent alerts:"] + [f"  {a}" for a in self.alerts]
        out += ["", "Events:"] + [f"  {e}" for e in self.events]
        print("\n".join(out), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--out", default="data", help="folder for heartbeats.csv / alerts.csv")
    args = ap.parse_args()

    r = Receiver(args.out)

    def on_connect(client, userdata, flags, rc, *extra):  # works with paho 1.x and 2.x
        r.connected = True
        client.subscribe("dogs/#", qos=1)

    def on_disconnect(client, userdata, *extra):
        r.connected = False

    def on_message(client, userdata, m):
        r.on_message(m.topic, m.payload.decode(errors="replace"))

    if hasattr(mqtt, "CallbackAPIVersion"):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dog-receiver",
                             clean_session=False)
    else:
        client = mqtt.Client(client_id="dog-receiver", clean_session=False)
    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.connect_async(args.broker, args.port, keepalive=10)
    client.loop_start()
    try:
        while True:
            r.draw()
            time.sleep(1)
    except KeyboardInterrupt:
        client.loop_stop()
        print(f"\nstopped. hb={r.counts['hb']} alerts={r.counts['alert']} seq gaps={r.gaps}")


if __name__ == "__main__":
    main()
