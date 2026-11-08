"""Night build tests. Run: ~/forge/.venv/bin/python -m pytest -q night/tests"""
import importlib, json, os, sys, time
from pathlib import Path
import numpy as np
import pytest

N = Path(__file__).resolve().parent.parent
for d in ("tap3", "fusion", "map", "dog"):
    sys.path.insert(0, str(N / d))


# ---------------- tap3 ----------------
def test_tap3_patterns():
    import detect
    k = lambda tt: [e["kind"] for e in detect.detect(detect.synth_taps(tap_times=tt), 16000)["events"]]  # noqa: E731
    assert "confirmed" in k((1, 2, 3, 6.5, 7.5, 8.5))
    assert k((2, 3, 4)) == ["pattern"]
    assert k((1, 2, 3, 4, 5, 6)) == []          # steady beat (footsteps-like) rejected by the guard
    assert k((2, 3)) == [] and k((1, 2, 3.5)) == [] and k(()) == []


def test_tap3_interval_bounds():
    import detect
    k = lambda tt: [e["kind"] for e in detect.detect(detect.synth_taps(dur=14, tap_times=tt), 16000)["events"]]  # noqa: E731
    assert k((1, 1.3, 1.6)) == []                # 0.3 s gaps: too fast
    assert k((1, 3, 5)) == []                    # 2 s gaps: too slow


# ---------------- fusion (HTTP level) ----------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHT_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setenv("NIGHT_EVIDENCE", str(tmp_path / "ev"))
    for m in ("fuse", "inbox", "aar"):
        sys.modules.pop(m, None)
    import fuse
    from fastapi.testclient import TestClient
    return TestClient(fuse.make_app()), fuse


def _wait(c, n, timeout=5):
    t = time.time()
    while time.time() - t < timeout:
        if len(c.get("/contacts").json()) >= n:
            return
        time.sleep(0.1)
    raise AssertionError("contacts not created")


def test_fusion_confirm_cot_chain(client):
    c, fuse = client
    import inbox
    t = time.time()
    inbox.emit("dog1", "dog_stop", 0.3, {"x": 5.2, "y": 3.6}, t=t)
    inbox.emit("tap3", "tap_pattern_3", 0.95, {"x": 5.3, "y": 3.85}, t=t + 3)
    inbox.emit("uav1", "thermal_person", 0.7, {"lat": 41.3035, "lon": -81.7530}, t=t + 4)
    _wait(c, 2)
    cs = c.get("/contacts").json()
    floor = [x for x in cs if x["frame"] == "floor"][0]
    assert {s["sensor"] for s in floor["sources"]} == {"dog1", "tap3"}
    assert abs(floor["p_person"] - (1 - (1 - .3 * .3) * (1 - .85 * .95))) < 1e-3
    assert floor["status"] == "candidate"
    r = c.post("/confirm", json={"contact_id": floor["contact_id"], "operator_id": "op1"})
    assert r.status_code == 200 and r.json()["cot_valid"], r.text
    assert c.post("/confirm", json={"contact_id": "C99", "operator_id": "op1"}).status_code == 404
    assert c.post("/confirm", json={"contact_id": floor["contact_id"], "operator_id": ""}).status_code == 422
    xml = c.get(f"/cot/{floor['contact_id']}").text
    assert 'type="a-h-G"' in xml and "op1" in xml
    v = c.get("/verify").json()
    assert v["ok"] and v["records"] >= 6


def test_chain_tamper_detected(client, tmp_path):
    c, fuse = client
    c.post("/event", json={"type": "note", "payload": {"a": 1}})
    c.post("/event", json={"type": "note", "payload": {"a": 2}})
    lines = fuse.CHAIN.read_text().splitlines()
    r = json.loads(lines[0]); r["payload"]["a"] = 99; lines[0] = json.dumps(r)
    bad = tmp_path / "bad.jsonl"; bad.write_text("\n".join(lines) + "\n")
    assert not fuse.verify_chain(bad)["ok"]
    assert fuse.verify_chain()["ok"]


def test_inbox_rejects_malformed(client):
    c, fuse = client
    fuse.INBOX.mkdir(parents=True, exist_ok=True)
    (fuse.INBOX / "x.json").write_text("{not json")
    (fuse.INBOX / "y.json").write_text(json.dumps({"t": 1, "sensor": "s", "kind": "k", "confidence": 7}))
    t = time.time()
    while time.time() - t < 4 and len(list((fuse.INBOX / "rejected").glob("*.json"))) < 2:
        time.sleep(0.1)
    assert len(list((fuse.INBOX / "rejected").glob("*.json"))) == 2
    assert any(r["type"] == "inbox_rejected" for r in c.get("/chain").json())


def test_cot_xsd_rejects_bad_lat():
    sys.modules.pop("fuse", None)
    import fuse
    x = fuse.cot_xml({"contact_id": "C1", "lat": 200.0, "lon": 0.0, "ce_m": 5, "p_person": .5, "sources": [],
                      "operator_id": "o", "confirmed_at": "t"})
    assert not fuse.validate_cot(x)[0]


# ---------------- map model ----------------
def test_prior_matches_both_marginals():
    import model as M
    for name in ("child_autistic", "td_child_1_16"):
        pr, cv, cl, mass = M.prior(name)
        assert abs(pr.sum() - 1) < 1e-6
        p = M.PERSONAS[name]
        r = M.F["r"]
        for q, target in zip(p["q"], (0.25, 0.5, 0.75, 0.95)):
            assert abs(pr[r <= q].sum() - target) < 0.02, (name, q)
        for k, v in p["find"].items():
            assert abs(mass[k] - v) < 1.0, (name, k)
        assert pr.min() > 0                      # never zeroed


def test_clue_and_negative_evidence():
    import model as M
    pr, *_ = M.prior("td_child_1_16")
    _, post, *_ = M.posterior("td_child_1_16", [{"type": "sound_contact", "e": 500, "n": 500}], None)
    r, c = M.en_cell(500, 500)
    assert post[r, c] > pr[r, c] * 5
    _, post2, *_ = M.posterior("td_child_1_16", [{"type": "searched_no_find", "e": 0, "n": 0, "radius_m": 300, "pod": 0.8}], None)
    r0, c0 = M.en_cell(0, 0)
    assert post2[r0, c0] < pr[r0, c0]
    assert abs(post2.sum() - 1) < 1e-6


# ---------------- dog pipeline on the synthetic run ----------------
def test_dog_synthetic_sync_and_track():
    run = N / "data/dog/run_00_synthetic"
    if not (run / "sync.json").exists():
        pytest.skip("synthetic run not processed")
    s = json.loads((run / "sync.json").read_text())
    assert abs(s["error_vs_truth_ms"]) < 40
    t = json.loads((run / "track_summary.json").read_text())
    assert t["vs_synthetic_truth_m"]["p95"] < 0.10
