"""Fusion service on :8140: inbox -> contacts -> human confirm -> CoT + hash-chained evidence log.

Inbox: night/inbox/*.json written by any sensor (see inbox.py): {t, sensor, kind, position, confidence, clip_path}.
  position {x, y[, frame:"floor"]} = floor metres; {lat, lon} = WGS-84. Both are converted to local
  metres east/north of the LKP using config.json (floor_anchor) so everything clusters in one frame.
Clustering: an event joins the nearest open contact within cluster_m (2 m floor / 25 m geo) whose
  last event is within cluster_window_s; else it starts a new contact.
Confidence: p_person = 1 - prod(1 - w_kind * max_conf(sensor, kind)), one term per (sensor, kind)
  so a dog stopping five times does not count five times.
Nothing becomes confirmed without POST /confirm {contact_id, operator_id}.
Evidence: every ingested detection, new contact, contact update, confirm, clear and CoT write is
  appended to night/evidence/chain.jsonl as {seq, ts, type, payload, prev, hash} with
  hash = sha256(prev + canonical_json({seq, ts, type, payload})). GET /verify re-walks the chain.
CoT: every contact is emitted as CoT, validated against the cot-validator XSD ("Marker - 2525.xsd"):
  candidate -> type a-u-G (unknown ground); after a human confirms, the SAME uid is re-emitted as
  a-f-G (friendly ground) so ATAK updates the pin in place. a-h-* (hostile) is refused: a survivor is not
  hostile. Files: evidence/cot/<uid>.xml (current) + <uid>.candidate.xml / <uid>.confirmed.xml; every
  write is chained (type, XSD result, sha256).

  python fuse.py [port]          # service
  python fuse.py --verify        # verify chain, exit 1 on break
"""
from __future__ import annotations
import hashlib, json, math, os, sys, threading, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
NIGHT = HERE.parent
CFG = json.loads((NIGHT / "config.json").read_text())
INBOX = Path(os.environ.get("NIGHT_INBOX", NIGHT / "inbox"))
EVID = Path(os.environ.get("NIGHT_EVIDENCE", NIGHT / "evidence"))
CHAIN = EVID / "chain.jsonl"
XSD = Path.home() / "forge/datasets/cot/cot-validator/validator/schemas/Marker - 2525.xsd"
R_EARTH = 6371008.8


# ---------------- geometry ----------------
def ll_to_en(lat, lon):
    lat0, lon0 = CFG["lkp"]["lat"], CFG["lkp"]["lon"]
    e = math.radians(lon - lon0) * R_EARTH * math.cos(math.radians(lat0))
    n = math.radians(lat - lat0) * R_EARTH
    return e, n


def en_to_ll(e, n):
    lat0, lon0 = CFG["lkp"]["lat"], CFG["lkp"]["lon"]
    return lat0 + math.degrees(n / R_EARTH), lon0 + math.degrees(e / (R_EARTH * math.cos(math.radians(lat0))))


def floor_to_en(x, y):
    a = CFG["floor_anchor"]; e0, n0 = ll_to_en(a["lat"], a["lon"])
    r = math.radians(a.get("rotation_deg", 0.0))
    # floor +x east, +y south (image down); rotate clockwise by r
    k = float(a.get("scale", 1.0))          # demo scaling, see config.json
    de, dn = x * k, -y * k
    return e0 + de * math.cos(r) + dn * math.sin(r), n0 - de * math.sin(r) + dn * math.cos(r)


def position_en(pos: dict):
    if pos and "lat" in pos and "lon" in pos:
        return (*ll_to_en(float(pos["lat"]), float(pos["lon"])), "geo")
    if pos and pos.get("x") is not None and pos.get("y") is not None:
        return (*floor_to_en(float(pos["x"]), float(pos["y"])), "floor")
    return None


# ---------------- hash chain ----------------
class Chain:
    def __init__(self, path: Path):
        self.path = path; path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock(); self.seq = 0; self.prev = "0" * 64
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line); self.seq = r["seq"]; self.prev = r["hash"]

    @staticmethod
    def digest(prev, body):
        return hashlib.sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()

    def append(self, typ: str, payload: dict) -> dict:
        with self.lock:
            body = {"seq": self.seq + 1, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "type": typ, "payload": payload}
            h = self.digest(self.prev, body)
            rec = {**body, "prev": self.prev, "hash": h}
            with open(self.path, "a") as f:
                f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n"); f.flush(); os.fsync(f.fileno())
            self.seq += 1; self.prev = h
            return rec


def verify_chain(path: Path = CHAIN) -> dict:
    prev = "0" * 64; n = 0
    if not path.exists():
        return {"ok": True, "records": 0}
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        body = {k: r[k] for k in ("seq", "ts", "type", "payload")}
        if r["prev"] != prev or Chain.digest(prev, body) != r["hash"] or r["seq"] != n + 1:
            return {"ok": False, "records": n, "broken_at_line": i, "seq": r.get("seq")}
        prev = r["hash"]; n += 1
    return {"ok": True, "records": n, "head": prev}


# ---------------- CoT ----------------
def cot_type(status: str) -> str:
    cc = CFG["cot"]
    t = cc["type_confirmed"] if status == "confirmed" else cc["type_candidate"]
    if t.lower().startswith("a-h"):
        raise ValueError(f"refusing CoT type {t}: a survivor is not hostile (use a-u-G / a-f-G)")
    return t


for _st in ("candidate", "confirmed"):      # fail at start-up, not mid-demo, if the config is wrong
    cot_type(_st)


def cot_xml(c: dict) -> str:
    now = datetime.now(timezone.utc)
    f = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  # noqa: E731
    cc = CFG["cot"]; uid = cc["uid_prefix"] + c["contact_id"]
    typ = cot_type(c.get("status", "candidate"))
    srcs = ", ".join(f"{s['sensor']}:{s['kind']}={s['confidence']:.2f}" for s in c["sources"])
    who = (f"CONFIRMED by {c['operator_id']} at {c['confirmed_at']}" if c.get("status") == "confirmed"
           else "UNCONFIRMED candidate: machine detection, awaiting human confirm")
    remarks = f"p_person={c['p_person']:.2f}; sources: {srcs}; {who}; evidence chain seq {c.get('chain_seq')}" 
    from xml.sax.saxutils import quoteattr, escape
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<event version="2.0" uid={quoteattr(uid)} type="{typ}" time="{f(now)}" start="{f(now)}" '
            f'stale="{f(now + timedelta(minutes=cc["stale_min"]))}" how="{cc["how"]}">'
            f'<point lat="{c["lat"]:.7f}" lon="{c["lon"]:.7f}" hae="9999999.0" ce="{c["ce_m"]:.1f}" le="9999999.0"/>'
            f'<detail><contact callsign={quoteattr("LF " + c["contact_id"] + " p=" + format(c["p_person"], ".2f"))}/>'
            f'<remarks>{escape(remarks)}</remarks></detail></event>\n')


_schema = None


def validate_cot(xml: str) -> tuple[bool, str]:
    global _schema
    from lxml import etree
    if _schema is None:
        _schema = etree.XMLSchema(etree.parse(str(XSD)))
    doc = etree.fromstring(xml.encode())
    ok = _schema.validate(doc)
    return ok, "valid" if ok else str(_schema.error_log.last_error)


# ---------------- fusion state ----------------
class Fusion:
    def __init__(self):
        self.chain = Chain(CHAIN)
        self.lock = threading.RLock()
        self.contacts: dict[str, dict] = {}
        self.detections: list[dict] = []
        self.n = 0
        self.t0 = None
        self._replay_state()

    def _replay_state(self):
        """Rebuild contacts from the chain so a restart loses nothing."""
        if not CHAIN.exists():
            return
        for line in CHAIN.read_text().splitlines():
            r = json.loads(line)
            if r["type"] in ("contact_new", "contact_update", "contact_confirmed", "contact_cleared"):
                c = r["payload"]["contact"]; self.contacts[c["contact_id"]] = c
                self.n = max(self.n, int(c["contact_id"][1:]))
            elif r["type"] == "detection":
                self.detections.append(r["payload"])

    def weight(self, kind: str) -> float:
        w = CFG["modality_weight"]; return w.get(kind, w["default"])

    def ingest(self, det: dict, src_file: str | None = None) -> dict | None:
        with self.lock:
            p = position_en(det.get("position") or {})
            rec = self.chain.append("detection", {**det, "inbox_file": src_file})
            det = {**det, "chain_seq": rec["seq"]}
            self.detections.append(det)
            if self.t0 is None or det["t"] < self.t0:
                self.t0 = det["t"]
            if p is None:
                return None        # no position -> logged, not clustered
            e, n, frame = p
            r = CFG["cluster_m"][frame] * (float(CFG["floor_anchor"].get("scale", 1.0)) if frame == "floor" else 1.0)
            best, bd = None, 1e18
            for c in self.contacts.values():
                if c["status"] == "cleared" or det["t"] - c["last_seen"] > CFG["cluster_window_s"]:
                    continue
                d = math.hypot(c["e"] - e, c["n"] - n)
                if d <= max(r, c["ce_m"]) and d < bd:
                    best, bd = c, d
            if best is None:
                self.n += 1
                cid = f"C{self.n:02d}"
                best = {"contact_id": cid, "e": e, "n": n, "frame": frame, "sources": [], "events": [],
                        "first_seen": det["t"], "last_seen": det["t"], "status": "candidate",
                        "operator_id": None, "confirmed_at": None}
                self.contacts[cid] = best; typ = "contact_new"
            else:
                typ = "contact_update"
            best["events"].append(det["chain_seq"])
            best["last_seen"] = max(best["last_seen"], det["t"])
            # update position: confidence-weighted mean of member events
            k = len(best["events"]); wgt = max(det["confidence"], 0.05)
            best.setdefault("_wsum", 0.0)
            best["e"] = (best["e"] * best["_wsum"] + e * wgt) / (best["_wsum"] + wgt) if best["_wsum"] else e
            best["n"] = (best["n"] * best["_wsum"] + n * wgt) / (best["_wsum"] + wgt) if best["_wsum"] else n
            best["_wsum"] += wgt
            key = (det["sensor"], det["kind"])
            for s in best["sources"]:
                if (s["sensor"], s["kind"]) == key:
                    s["confidence"] = max(s["confidence"], det["confidence"]); s["n"] += 1; break
            else:
                best["sources"].append({"sensor": det["sensor"], "kind": det["kind"], "confidence": det["confidence"], "n": 1})
            q = 1.0
            for s in best["sources"]:
                q *= 1 - self.weight(s["kind"]) * s["confidence"]
            best["p_person"] = round(1 - q, 4)
            fs = float(CFG["floor_anchor"].get("scale", 1.0))
            best["ce_m"] = round(1.0 * fs if frame == "floor" else 10.0 if k > 1 else 25.0, 1)
            best["lat"], best["lon"] = en_to_ll(best["e"], best["n"])
            rec = self.chain.append(typ, {"contact": self.public(best), "by_detection": det["chain_seq"]})
            best["chain_seq"] = rec["seq"]
            self.write_cot(best)       # a-u-G while candidate; a confirmed contact stays a-f-G on updates
            return best

    def write_cot(self, c: dict) -> dict:
        xml = cot_xml(c)
        ok, msg = validate_cot(xml)
        out = EVID / "cot"; out.mkdir(parents=True, exist_ok=True)
        base = f"{CFG['cot']['uid_prefix']}{c['contact_id']}"
        path = out / f"{base}.xml"; path.write_text(xml)
        (out / f"{base}.{c.get('status', 'candidate')}.xml").write_text(xml)
        typ = cot_type(c.get("status", "candidate"))
        self.chain.append("cot_written", {"contact_id": c["contact_id"], "type": typ, "status": c.get("status"),
                                          "path": str(path), "xsd": XSD.name, "valid": ok, "detail": msg,
                                          "sha256": hashlib.sha256(xml.encode()).hexdigest()})
        return {"cot_path": str(path), "cot_valid": ok, "cot_detail": msg, "cot_type": typ}

    def public(self, c):
        return {k: v for k, v in c.items() if not k.startswith("_")}

    def confirm(self, cid, operator_id):
        with self.lock:
            c = self.contacts.get(cid)
            if not c:
                raise KeyError(cid)
            if not operator_id or len(operator_id) > 64:
                raise ValueError("operator_id required (<= 64 chars)")
            c["status"] = "confirmed"; c["operator_id"] = operator_id
            c["confirmed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rec = self.chain.append("contact_confirmed", {"contact": self.public(c), "operator_id": operator_id})
            c["chain_seq"] = rec["seq"]
            return {"contact": self.public(c), **self.write_cot(c)}     # same uid re-emitted as a-f-G

    def clear(self, cid, operator_id, reason=""):
        with self.lock:
            c = self.contacts[cid]; c["status"] = "cleared"; c["operator_id"] = operator_id
            self.chain.append("contact_cleared", {"contact": self.public(c), "operator_id": operator_id, "reason": reason[:200]})
            return self.public(c)


def watch(fu: Fusion, stop: threading.Event):
    done = INBOX / "processed"; bad = INBOX / "rejected"
    done.mkdir(parents=True, exist_ok=True); bad.mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        done.mkdir(parents=True, exist_ok=True); bad.mkdir(parents=True, exist_ok=True)   # survive an archive moving them away
        for f in sorted(INBOX.glob("*.json")):
            try:
                d = json.loads(f.read_text())
                for k in ("t", "sensor", "kind", "confidence"):
                    if k not in d:
                        raise ValueError(f"missing {k}")
                d["t"] = float(d["t"]); d["confidence"] = float(d["confidence"])
                if not (0 <= d["confidence"] <= 1) or not math.isfinite(d["t"]):
                    raise ValueError("confidence/t out of range")
                fu.ingest(d, f.name); f.rename(done / f.name)
            except Exception as e:  # malformed drop -> rejected/, logged on the chain
                fu.chain.append("inbox_rejected", {"file": f.name, "error": str(e)[:200]})
                try:
                    f.rename(bad / f.name)
                except OSError:
                    pass                   # file already moved/archived: never let the watcher thread die
        stop.wait(0.3)


from pydantic import BaseModel


class Confirm(BaseModel):     # module level: with postponed annotations FastAPI cannot see a class local to make_app
    contact_id: str
    operator_id: str
    reason: str = ""


def make_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    fu = Fusion(); stop = threading.Event()
    threading.Thread(target=watch, args=(fu, stop), daemon=True).start()
    app = FastAPI(title="night fusion")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health():
        return {"ok": True, "contacts": len(fu.contacts), "chain_seq": fu.chain.seq}

    @app.get("/contacts")
    def contacts():
        return sorted((fu.public(c) for c in fu.contacts.values()), key=lambda c: -c.get("p_person", 0))

    @app.get("/detections")
    def detections(limit: int = 200):
        return fu.detections[-limit:]

    @app.post("/confirm")
    def confirm(b: Confirm):
        try:
            return fu.confirm(b.contact_id, b.operator_id)
        except KeyError:
            raise HTTPException(404, "no such contact")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.post("/clear")
    def clear(b: Confirm):
        if b.contact_id not in fu.contacts:
            raise HTTPException(404)
        return fu.clear(b.contact_id, b.operator_id, b.reason)

    @app.post("/ingest")
    def ingest(d: dict):
        """Direct ingest (same schema as an inbox file), for sensors that would rather POST."""
        import inbox
        p = inbox.emit(d["sensor"], d["kind"], float(d["confidence"]), d.get("position"), d.get("clip_path"), d.get("t"), d.get("extra"))
        return {"queued": p.name}

    MAP = "http://127.0.0.1:8143"

    @app.get("/nba")
    def nba_get():
        """Next Best Action computed by the map service on the current COP (proxied). Hint only."""
        import urllib.request
        try:
            return json.loads(urllib.request.urlopen(MAP + "/api/nba", timeout=5).read())
        except Exception as e:
            return {"none": True, "error": f"map service not reachable ({type(e).__name__})"}

    @app.post("/nba/decision")
    def nba_decision(d: dict):
        """Operator decision on a suggestion. Chained with the operator id. Accept writes a search-point
        CoT (b-m-p-w, waypoint) for the suggested cell; NOTHING is sent to any asset (hints only)."""
        import urllib.request
        dec = d.get("decision"); op = str(d.get("operator_id", "")).strip()[:64]; nba = d.get("nba") or {}
        if dec not in ("accept", "dismiss") or not op or "cell" not in nba:
            raise HTTPException(422, "need decision accept|dismiss, operator_id and an nba with a cell")
        rec = fu.chain.append("nba_decision", {"decision": dec, "operator_id": op, "nba": nba, "persona": d.get("persona"),
                                               "note": "hint only; no asset was tasked by the system"})
        out = {"chained_seq": rec["seq"], "hash": rec["hash"], "decision": dec}
        if dec == "accept":
            from xml.sax.saxutils import quoteattr, escape
            now = datetime.now(timezone.utc); f = lambda x: x.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  # noqa: E731
            uid = f"{CFG['cot']['uid_prefix']}NBA-{rec['seq']}"
            asset = nba.get("asset", "drone")
            rem = (f"Suggested search point {nba.get('cell_id')} accepted by {op}: {asset}, ETA "
                   f"{nba.get(asset, {}).get('eta_min')} min; P(cell)={nba.get('p', 0):.4f}. Operator to task the asset; "
                   f"not an automatic order. Evidence chain seq {rec['seq']}")
            xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<event version="2.0" uid={quoteattr(uid)} type="b-m-p-w" '
                   f'time="{f(now)}" start="{f(now)}" stale="{f(now + timedelta(minutes=60))}" how="h-e">'
                   f'<point lat="{nba["lat"]:.7f}" lon="{nba["lon"]:.7f}" hae="9999999.0" ce="{CFG.get("nba_ce_m", 35.0):.1f}" le="9999999.0"/>'
                   f'<detail><contact callsign={quoteattr("NBA " + str(nba.get("cell_id")))}/><remarks>{escape(rem)}</remarks></detail></event>\n')
            ok, msg = validate_cot(xml)
            cdir = EVID / "cot"; cdir.mkdir(parents=True, exist_ok=True)
            path = cdir / f"{uid}.xml"; path.write_text(xml)
            fu.chain.append("cot_written", {"contact_id": f"NBA-{rec['seq']}", "type": "b-m-p-w", "status": "nba_accepted",
                                            "path": str(path), "xsd": XSD.name, "valid": ok, "detail": msg,
                                            "sha256": hashlib.sha256(xml.encode()).hexdigest()})
            out.update({"cot_path": str(path), "cot_valid": ok, "cot_uid": uid})
        try:
            req = urllib.request.Request(MAP + "/api/nba/mark", headers={"content-type": "application/json"},
                                         data=json.dumps({"decision": dec, "operator_id": op, "nba": nba, "seq": rec["seq"],
                                                          "t": time.time(), "cot_uid": out.get("cot_uid")}).encode())
            urllib.request.urlopen(req, timeout=2).read()
        except Exception:
            out["map_notified"] = False
        return out

    @app.post("/event")
    def event(d: dict):
        """Append a typed event from another service (map clue, persona change...) to the chain."""
        typ = str(d.get("type", ""))[:40]
        if not typ.replace("_", "").isalnum():
            raise HTTPException(422, "type must be [a-z0-9_]")
        return fu.chain.append("ext_" + typ, d.get("payload", {}))

    @app.post("/mission_start")
    def mission_start(d: dict | None = None):
        """Marks t0 for the AAR (time-to-first-contact is measured from here)."""
        return fu.chain.append("mission_start", {"t": time.time(), "note": (d or {}).get("note", "")[:200]})

    @app.get("/chain")
    def chain(tail: int = 50):
        if not CHAIN.exists():
            return []
        return [json.loads(x) for x in CHAIN.read_text().splitlines()[-tail:]]

    @app.get("/verify")
    def verify():
        return verify_chain()

    @app.get("/cot/{cid}")
    def cot(cid: str):
        from fastapi.responses import PlainTextResponse
        p = EVID / "cot" / f"{CFG['cot']['uid_prefix']}{cid}.xml"
        if not p.exists() or p.parent != (EVID / "cot"):
            raise HTTPException(404)
        return PlainTextResponse(p.read_text(), media_type="application/xml")

    @app.get("/aar")
    def aar():
        import aar as A
        return A.compute()

    @app.get("/", response_class=__import__("fastapi").responses.HTMLResponse)
    def index():
        return (HERE / "console.html").read_text()

    return app


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    if "--verify" in sys.argv:
        r = verify_chain(); print(json.dumps(r)); sys.exit(0 if r["ok"] else 1)
    import uvicorn
    port = int(next((a for a in sys.argv[1:] if a.isdigit()), 8140))
    uvicorn.run(make_app(), host="0.0.0.0", port=port, log_level="warning")
