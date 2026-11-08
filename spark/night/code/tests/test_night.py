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
    cand = c.get(f"/cot/{floor['contact_id']}").text            # unconfirmed contact -> a-u-G, XSD-valid
    assert 'type="a-u-G"' in cand and "UNCONFIRMED" in cand
    assert fuse.validate_cot(cand)[0]
    r = c.post("/confirm", json={"contact_id": floor["contact_id"], "operator_id": "op1"})
    assert r.status_code == 200 and r.json()["cot_valid"] and r.json()["cot_type"] == "a-f-G", r.text
    assert c.post("/confirm", json={"contact_id": "C99", "operator_id": "op1"}).status_code == 404
    assert c.post("/confirm", json={"contact_id": floor["contact_id"], "operator_id": ""}).status_code == 422
    xml = c.get(f"/cot/{floor['contact_id']}").text            # same uid re-emitted as friendly
    assert 'type="a-f-G"' in xml and "CONFIRMED by op1" in xml
    uid = 'uid="NIGHT-' + floor["contact_id"] + '"'
    assert uid in xml and uid in cand
    assert "a-h" not in xml and "a-h" not in cand
    types = [x["payload"]["type"] for x in c.get("/chain?tail=500").json() if x["type"] == "cot_written"]
    assert "a-u-G" in types and types[-1] == "a-f-G" and not any(t.startswith("a-h") for t in types)
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


def test_cot_xsd_and_type_guard(monkeypatch):
    sys.modules.pop("fuse", None)
    import fuse
    base = {"contact_id": "C1", "lat": 41.3, "lon": -81.75, "ce_m": 5, "p_person": .5, "sources": [],
            "operator_id": "o", "confirmed_at": "t"}
    for st, typ in (("candidate", "a-u-G"), ("confirmed", "a-f-G")):
        x = fuse.cot_xml({**base, "status": st})
        assert f'type="{typ}"' in x and fuse.validate_cot(x)[0]
    assert not fuse.validate_cot(fuse.cot_xml({**base, "lat": 200.0}))[0]        # XSD rejects bad lat
    monkeypatch.setitem(fuse.CFG["cot"], "type_confirmed", "a-h-G")              # hostile is refused
    with pytest.raises(ValueError):
        fuse.cot_xml({**base, "status": "confirmed"})


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


# ---------------- Phase 7: orchestrator (COP fields, coverage, next best action) ----------------
def _cfg():
    return json.loads((N / "config.json").read_text())


def _grid():
    import cop
    c = _cfg()
    return cop.Grid(100, 50.0, 2500.0, c["lkp"]["lat"], c["lkp"]["lon"])


def test_field_summation():
    import cop
    g, cfg = _grid(), _cfg()
    assert abs(g.gaussian(0, 0, 200).sum() - 1) < 1e-3          # unit mass kernel on the grid
    assert abs(g.disk(300, 300, 80).sum() - 1) < 1e-9
    assert g.gaussian(1e6, 1e6, 100).sum() < 1e-9               # off-grid mass is dropped, not squeezed in
    f2e = lambda x, y: (x * 100.0, -y * 100.0)                  # noqa: E731
    tap = cop.event_field({"sensor": "tap3", "kind": "tap_pattern_3", "confidence": 1.0, "position": {"lat": cfg["lkp"]["lat"], "lon": cfg["lkp"]["lon"]},
                           "extra": {"strength": 10.0}}, g, cfg, f2e)
    weak = cop.event_field({"sensor": "tap3", "kind": "tap_pattern_3", "confidence": 1.0, "position": {"lat": cfg["lkp"]["lat"], "lon": cfg["lkp"]["lon"]},
                            "extra": {"strength": 2.0}}, g, cfg, f2e)
    assert tap["source"] == "tap3" and weak["sigma"] > tap["sigma"]      # sigma ~ 1 / signal strength
    assert abs(tap["field"].sum() - 0.85) < 0.01                         # mass = weight 0.85 x confidence 1.0
    dog = cop.event_field({"sensor": "dog1", "kind": "dog_stop", "confidence": 0.3, "position": {"x": 3, "y": 4}}, g, cfg, f2e)
    L = cop.sum_fields([tap, weak, dog], g.E.shape)
    assert np.allclose(L["tap3"], tap["field"] + weak["field"]) and np.allclose(L["dog"], dog["field"])
    base = np.ones(g.E.shape)
    c = cop.cop(base, L, None)
    assert abs(c.sum() - 1) < 1e-9
    r, k = g.cell_of(0, 0)
    assert c[r, k] > cop.cop(base, {}, None)[r, k] * 10                  # the tap pulls mass to the sensor
    c_off = cop.cop(base, L, None, enabled={"dog"})                     # toggling a source off removes it
    assert c_off[r, k] < c[r, k] / 10


def test_coverage_subtraction():
    import cop
    g = _grid()
    shots = [{"t_rel": 0, "e": 0, "n": 0, "footprint_m": [200, 200]}, {"t_rel": 10, "e": 50, "n": 0, "footprint_m": [200, 200]},
             {"t_rel": 99, "e": 2000, "n": 2000, "footprint_m": [200, 200]}]
    pd = cop.drone_pod(shots, 20, g, 0.6)
    r, k = g.cell_of(25, 25)
    assert abs(pd[r, k] - (1 - 0.4 ** 2)) < 1e-9                        # two passes: 1 - (1-p)^2
    r2, k2 = g.cell_of(2000, 2000)
    assert pd[r2, k2] == 0                                              # shot after t=20 not flown yet
    team = cop.disk_pod([{"e": 25, "n": 25, "radius_m": 100, "pod": 0.5}], g)
    tot = cop.combine_pod(pd, None, team)
    assert abs(tot[r, k] - (1 - 0.4 ** 2 * 0.5)) < 1e-9                 # independent sweeps combine
    base = np.ones(g.E.shape)
    c = cop.cop(base, {}, tot)
    ratio = c[r, k] / c[0, 0]
    assert abs(ratio - (1 - tot[r, k])) < 1e-9 and abs(c.sum() - 1) < 1e-9


def test_next_best_action_selection():
    import cop
    g, cfg = _grid(), _cfg()
    c = np.full(g.E.shape, 1.0)
    a = g.cell_of(500, 0); b = g.cell_of(-1000, 0); d = g.cell_of(0, 1500)
    c[a] = 100; c[b] = 50; c[d] = 20
    c = c / c.sum()
    nba = cop.next_best_action(c, None, g, cfg)
    assert tuple(nba["cell"]) == a
    pod = np.zeros(g.E.shape); pod[a] = 0.5                            # searched (POD >= 0.3) -> skipped
    nba = cop.next_best_action(c, pod, g, cfg)
    assert tuple(nba["cell"]) == b
    nba = cop.next_best_action(c, pod, g, cfg, tasked={b})             # already tasked -> skipped
    assert tuple(nba["cell"]) == d
    A = cfg["assets"]; de, dn = g.ll2en(A["drone"]["lat"], A["drone"]["lon"])
    dist = np.hypot(nba["e"] - de, nba["n"] - dn)
    assert abs(nba["drone"]["eta_min"] - round((A["drone"]["launch_s"] + dist / A["drone"]["speed_mps"]) / 60, 1)) < 0.11
    assert nba["team"]["eta_min"] > nba["drone"]["eta_min"] and nba["asset"] == "drone"
    assert nba["text"].startswith("Suggest: drone to ")


def test_field_cap_50_dog_alerts():
    import cop
    g, cfg = _grid(), _cfg()
    f2e = lambda x, y: (x * 100.0, -y * 100.0)                  # noqa: E731
    rng = np.random.default_rng(0)
    dets = [{"sensor": "dog1", "kind": "knock", "confidence": 0.9, "position": {"x": float(rng.uniform(0, 6)), "y": float(rng.uniform(0, 4))}}
            for _ in range(50)]
    dets.append({"sensor": "tap3", "kind": "tap_pattern_3", "confidence": 0.4, "position": {"x": 1.0, "y": 1.0}, "extra": {"strength": 5}})
    fl = [cop.event_field(d, g, cfg, f2e) for d in dets]
    raw = cop.sum_fields(fl, g.E.shape)
    cap = cfg["fields"]["source_cap_frac"]
    assert raw["dog"].sum() > 10 * cap                                   # uncapped, 50 alerts would swamp the prior
    capped, info = cop.cap_layers(raw, cap, 1.0)
    assert capped["dog"].sum() <= cap + 1e-9 and info["dog"]["scale"] < 1
    assert np.allclose(capped["tap3"], raw["tap3"]) and info["tap3"]["scale"] == 1.0   # under the cap: untouched
    c = cop.cop(np.ones(g.E.shape), capped, None)
    # the dog's share of the COP is at most cap / (1 + cap + tap mass)
    share = capped["dog"].sum() / (1 + sum(L.sum() for L in capped.values()))
    assert share <= cap / (1 + cap) + 1e-9 and abs(c.sum() - 1) < 1e-9
