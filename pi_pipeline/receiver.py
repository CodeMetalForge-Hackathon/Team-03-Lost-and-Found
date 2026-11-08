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


NUMERIC = ["activity", "temp_c", "humidity", "therm_c", "dist_cm"]


class Receiver:
    def __init__(self, outdir, since=None):
        os.makedirs(outdir, exist_ok=True)
        self.since = since                    # epoch seconds: drop readings taken before this
        self.skipped = 0
        self.ranges = {}                      # field -> [min, max] over HB rows
        self.alert_types = collections.Counter()
        self.first_seq = self.restarts = self.dups = 0
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
            taken = datetime.datetime.fromisoformat(msg["ts"]).timestamp()
        except (ValueError, KeyError, TypeError):
            self.events.append(f"bad message on {topic}: {payload[:60]!r}")
            return
        if kind not in self.writers:
            return
        if self.since and taken < self.since:  # --run: reading from before the run started
            self.skipped += 1
            return
        if not self.counts:
            self.first_seq = seq
        if kind == "hb":
            for field in NUMERIC:
                v = msg.get(field)
                if v is not None:
                    lo, hi = self.ranges.get(field, (v, v))
                    self.ranges[field] = [min(lo, v), max(hi, v)]
        else:
            self.alert_types[msg.get("alert")] += 1
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
                self.dups += 1
                self.events.append(f"duplicate/out-of-order {dog}: seq {seq} after {last}")
                return  # keep last_seq
            else:
                self.restarts += 1
                self.events.append(f"{dog} seq reset {last} -> {seq} (board restarted?)")
        self.last_seq[dog] = seq

    def summary(self, name, outdir, stopped):
        """Write run.json for a --run recording."""
        info = {
            "run": name, "folder": outdir,
            "start": datetime.datetime.fromtimestamp(self.since).astimezone().isoformat(timespec="seconds"),
            "stop": datetime.datetime.fromtimestamp(stopped).astimezone().isoformat(timespec="seconds"),
            "duration_s": round(stopped - self.since, 1),
            "heartbeats": self.counts["hb"], "alerts": self.counts["alert"],
            "alerts_by_type": dict(self.alert_types),
            "first_seq": self.first_seq, "last_seq": max(self.last_seq.values(), default=None),
            "seq_gaps": self.gaps, "duplicates": self.dups, "board_restarts": self.restarts,
            "ranges": self.ranges,  # min/max per field over the run's heartbeats
        }
        with open(os.path.join(outdir, "run.json"), "w") as f:
            json.dump(info, f, indent=2)
        return info

    def draw(self, run=None):
        now = time.time()
        while self.arrivals and now - self.arrivals[0] > 10:
            self.arrivals.popleft()
        out = ["\033[H\033[J"]  # clear screen
        if run:
            out.append(f"RECORDING run '{run}'  {int(now - self.since) // 60:02d}:{int(now - self.since) % 60:02d}"
                       f"  -> Ctrl+C to stop and save")
        out += [
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
    ap.add_argument("--run", metavar="NAME", help="record one run into data/runs/NAME_<time>/ "
                    "(only readings taken from now until Ctrl+C); can run beside the main receiver")
    args = ap.parse_args()

    if args.run:
        started = time.time()
        args.out = os.path.join(args.out, "runs", f"{args.run}_{time.strftime('%Y%m%d-%H%M%S')}")
        r = Receiver(args.out, since=started)
    else:
        r = Receiver(args.out)

    def on_connect(client, userdata, flags, rc, *extra):  # works with paho 1.x and 2.x
        r.connected = True
        client.subscribe("dogs/#", qos=1)

    def on_disconnect(client, userdata, *extra):
        r.connected = False

    def on_message(client, userdata, m):
        r.on_message(m.topic, m.payload.decode(errors="replace"))

    # Main receiver: fixed id + persistent session, so the broker queues messages for it.
    # A --run recorder: broker-assigned id + clean session, so it never clashes with the main one.
    client_id, clean = ("", True) if args.run else ("dog-receiver", False)
    if hasattr(mqtt, "CallbackAPIVersion"):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=clean)
    else:
        client = mqtt.Client(client_id=client_id, clean_session=clean)
    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.connect_async(args.broker, args.port, keepalive=10)
    client.loop_start()
    try:
        while True:
            r.draw(args.run)
            time.sleep(1)
    except KeyboardInterrupt:
        client.loop_stop()
        print(f"\nstopped. hb={r.counts['hb']} alerts={r.counts['alert']} seq gaps={r.gaps}")
        if args.run:
            r.summary(args.run, args.out, time.time())
            print(f"run saved to {args.out}/ (heartbeats.csv, alerts.csv, run.json)")


if __name__ == "__main__":
    main()
