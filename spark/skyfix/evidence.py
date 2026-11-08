"""Sky Fix evidence: reuses rescuebase-forge's append-only SQLite event log (rb.store.Store, imported unchanged)
and its Cursor-on-Target builder (rb.cot.build_cot, imported unchanged).

Added here (not in rescuebase-forge): a SHA-256 hash chain. Every Sky Fix record carries
  prev_hash  = hash of the previous skyfix record (64 zeros for the first)
  hash       = sha256(prev_hash + canonical JSON of the record without 'hash')
so editing or deleting any past fix breaks verify(). A JSONL mirror is written next to the DB and verify() also
checks that the DB and the mirror end on the same head hash, so silently dropping the newest records from one copy
is detected (dropping them from both copies is not; the CoT files already handed off carry each record's hash).
CoT: one XML file per fix in skyfix/cot/, type a-f-G-U-C, uid SKYFIX-<n>, point ce = ring radius in metres,
validated against the TAK 'Marker - 2525.xsd' schema from datasets/cot/cot-validator if present.
NOTHING IS TRANSMITTED: files only. (rb.cot.send_udp is deliberately never imported.)
"""
from __future__ import annotations
import hashlib, json, pathlib, sys, threading, xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
RB = pathlib.Path.home() / "forge" / "rescuebase-forge"
if str(RB) not in sys.path:
    sys.path.insert(0, str(RB))
from rb.store import Store  # noqa: E402  (reused unchanged)
from rb.cot import build_cot, parse_cot  # noqa: E402  (reused unchanged)
from rb.schemas import Contact  # noqa: E402

XSD = pathlib.Path.home() / "forge/datasets/cot/cot-validator/validator/schemas/Marker - 2525.xsd"
GENESIS = "0" * 64
KIND = "skyfix_fix"


def _canon(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


class Evidence:
    def __init__(self, db_path=ROOT / "evidence" / "skyfix_evidence.db", cot_dir=ROOT / "cot"):
        self.store = Store(db_path)
        self.jsonl = pathlib.Path(db_path).with_suffix(".jsonl")
        self.cot_dir = pathlib.Path(cot_dir)
        self.cot_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._schema = None
        if XSD.exists():
            try:
                from lxml import etree
                self._schema = etree.XMLSchema(etree.parse(str(XSD)))
            except Exception as e:  # schema problems must not stop the fix
                self._schema_err = repr(e)

    def records(self):
        return [e["payload"] | {"_event_id": e["id"], "_ts": e["ts"]} for e in self.store.events(KIND)]

    def append(self, rec: dict) -> dict:
        import fcntl
        with self.lock, open(self.jsonl.with_suffix(".lock"), "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)  # the HTTP and HTTPS processes share one chain
            prev = self.records()
            n = len(prev) + 1
            body = dict(rec, seq=n, uid=f"SKYFIX-{n}", prev_hash=prev[-1]["hash"] if prev else GENESIS,
                        logged_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            body["hash"] = hashlib.sha256((body["prev_hash"] + _canon(body)).encode()).hexdigest()
            self.store.log_event(KIND, body)
            with open(self.jsonl, "a") as f:
                f.write(_canon(body) + "\n")
            return body

    def verify(self) -> dict:
        prev = GENESIS
        recs = self.records()
        for r in recs:
            r = {k: v for k, v in r.items() if not k.startswith("_")}
            h = r.pop("hash")
            if r["prev_hash"] != prev or hashlib.sha256((prev + _canon(r)).encode()).hexdigest() != h:
                return dict(ok=False, n=len(recs), broken_at=r.get("seq"))
            prev = h
        if self.jsonl.exists():
            lines = [l for l in self.jsonl.read_text().splitlines() if l.strip()]
            mhead = json.loads(lines[-1])["hash"] if lines else GENESIS
            if mhead != prev or len(lines) != len(recs):
                return dict(ok=False, n=len(recs), mirror_n=len(lines), broken_at="head mismatch between DB and JSONL mirror")
        return dict(ok=True, n=len(recs), head=prev)

    def write_cot(self, rec: dict) -> dict:
        """CoT file for a fix. Builds with rb.cot.build_cot, then sets Sky Fix type/uid/how."""
        now = datetime.now(timezone.utc)
        c = Contact(contact_id=str(rec["seq"]), lat=rec["lat"], lon=rec["lon"], ce_m=float(rec["ring_m"]), p_person=1.0,
                    sources=[rec["solver"]], first_seen=now.isoformat(), last_seen=now.isoformat(), status="candidate")
        xml = build_cot(c, stale_s=1800, now=now)
        ev = ET.fromstring(xml)
        ev.set("uid", rec["uid"]); ev.set("type", "a-f-G-U-C"); ev.set("how", "h-e")  # h-e: estimated (not GPS)
        det = ev.find("detail")
        det.find("contact").set("callsign", f"SKYFIX {rec['seq']}")
        det.find("remarks").text = (f"Sky Fix {rec['solver']} self-localisation, no GPS. ring={rec['ring_m']:.0f} m "
                                    f"heading={rec.get('heading_deg')} conf={rec.get('confidence')} hash={rec['hash'][:16]}")
        xml = ET.tostring(ev, encoding="unicode")
        path = self.cot_dir / f"{rec['uid']}.cot.xml"
        path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml)
        valid, err = None, None
        if self._schema is not None:
            from lxml import etree
            doc = etree.fromstring(xml.encode())
            valid = bool(self._schema.validate(doc))
            err = None if valid else str(self._schema.error_log.last_error)
        return dict(path=(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)), xsd=XSD.name if XSD.exists() else None, xsd_valid=valid,
                    xsd_error=err, parsed=parse_cot(xml), transmitted=False)


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    ev = Evidence(pathlib.Path(d) / "t.db", pathlib.Path(d) / "cot")
    r = ev.append(dict(solver="stars", lat=42.36, lon=-71.06, ring_m=35000.0, heading_deg=30.0, confidence="ok"))
    print(r["uid"], r["hash"][:16], ev.verify())
    print(ev.write_cot(r))
