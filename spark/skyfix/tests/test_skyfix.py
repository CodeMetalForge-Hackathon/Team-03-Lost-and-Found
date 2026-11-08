"""Sky Fix tests. Run: ~/forge/.venv/bin/python -m pytest -q tests"""
import json, math, pathlib, sys, tempfile
import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FR = ROOT / "synth" / "frames"


def test_renderer_gravity_matches_pointing():
    sys.path.insert(0, str(ROOT / "synth"))
    from render_sky import camera_axes
    r, d, f = camera_axes(30, 35, 5)
    g = np.array([np.dot([0, 0, -1], r), np.dot([0, 0, -1], d), np.dot([0, 0, -1], f)])
    assert math.isclose(math.degrees(math.asin(-g[2])), 35, abs_tol=1e-9)  # camera elevation recovered from gravity


def test_star_fix_exact_gravity():
    import solver_stars as S
    p = FR / "swiss_alps_az150_alt35.png"
    m = json.loads(p.with_suffix(".json").read_text())
    r = S.solve(str(p), utc=m["utc"].rstrip("Z"), gravity=m["gravity_cam"], tilt=0.0, elevation_m=m["elevation_m"])
    assert r["ok"] and r["fix"]
    e = math.hypot((r["fix"]["lat"] - m["lat"]) * 111.2, (r["fix"]["lon"] - m["lon"]) * 111.2 * math.cos(math.radians(m["lat"])))
    assert e < 3.0
    assert abs((r["fix"]["heading_deg"] - m["az"] + 180) % 360 - 180) < 0.2


def test_no_gravity_no_latitude():
    import solver_stars as S
    p = FR / "boston_az030_alt60.png"
    r = S.solve(str(p), utc="2026-11-08T04:44:14")
    assert r["ok"] and r["fix"] is None and "no latitude" in r["message"].lower()


def test_fov_from_f35_portrait():
    import solver_stars as S
    assert abs(S.fov_from_f35(27, 3000, 4000) - 51.3) < 0.5  # portrait 4:3, 27 mm-eq
    assert abs(S.fov_from_f35(27, 4000, 3000) - 65.4) < 0.5


def test_evidence_chain_and_tamper():
    from evidence import Evidence
    d = pathlib.Path(tempfile.mkdtemp())
    ev = Evidence(d / "e.db", d / "cot")
    for i in range(3):
        rec = ev.append(dict(solver="stars", lat=42 + i, lon=-71.0, ring_m=1000.0, heading_deg=1.0, confidence="x"))
    assert ev.verify()["ok"] and ev.verify()["n"] == 3
    c = ev.write_cot(rec)
    assert c["xsd_valid"] is True and c["parsed"]["type"] == "a-f-G-U-C" and c["parsed"]["uid"] == "SKYFIX-3" and c["parsed"]["ce"] == 1000.0
    # tamper with record 2 behind the store's back (bypass triggers by editing a copy of the DB)
    import sqlite3, shutil
    shutil.copy(d / "e.db", d / "t.db")
    db = sqlite3.connect(d / "t.db"); db.execute("DROP TRIGGER events_no_update")
    row = db.execute("SELECT id,payload FROM events WHERE id=2").fetchone()
    pl = json.loads(row[1]); pl["lat"] = 0.0
    db.execute("UPDATE events SET payload=? WHERE id=2", (json.dumps(pl),)); db.commit(); db.close()
    ev2 = Evidence(d / "t.db", d / "cot2")
    v = ev2.verify()
    assert v["ok"] is False and v["broken_at"] == 2


def test_cot_xsd_rejects_garbage():
    from evidence import Evidence
    d = pathlib.Path(tempfile.mkdtemp())
    ev = Evidence(d / "e.db", d / "cot")
    from lxml import etree
    assert not ev._schema.validate(etree.fromstring(b'<event version="2.0" uid="x" type="a-f-G-U-C"><detail/></event>'))


def test_device_to_camera():
    from app import device_to_camera_down
    # W3C: phone upright portrait, screen facing user, camera horizontal: accel up = +y device
    g = device_to_camera_down(0, 9.81, 0)
    assert np.allclose(g, [0, 9.81, 0])  # down = image down
    # phone flat, screen up, camera pointing at ground: accel = +z
    g = device_to_camera_down(0, 0, 9.81)
    assert np.allclose(g, [0, 0, 9.81])  # down = along the lens


def test_skyline_match_finds_planted_profile():
    import solver_skyline as SK
    rng = np.random.default_rng(0)
    prof = np.cumsum(rng.normal(0, 0.6, (50, 360)), 1); prof -= prof.mean(1, keepdims=True)
    j = np.arange(-25, 26); true_cell, true_psi = 17, 123
    e = prof[true_cell][(true_psi + j) % 360] + 3.0  # unknown pitch offset
    cs, psi, _ = SK.match(j, e, np.ones(len(j), bool), prof, "rms_detrend")
    assert cs.argmax() == true_cell and psi[true_cell] == true_psi


@pytest.fixture(scope="module")
def client():
    import os
    os.environ["SKYFIX_NO_WARM"] = "1"
    from fastapi.testclient import TestClient
    import app as A
    d = pathlib.Path(tempfile.mkdtemp())
    from evidence import Evidence
    A.EV = Evidence(d / "e.db", d / "cot")
    return TestClient(A.app)


def test_api_synth_and_errors(client):
    r = client.post("/api/solve", data={"demo_id": "synth:mojave_az270_alt60"}).json()
    assert r["ok"] and r["fix_out"] and r["evidence"]["uid"] == "SKYFIX-1" and r["cot"]["xsd_valid"]
    assert r["exact_err_km"] < 3 and r["recovery"]["ao"] == "MOJAVE"
    assert client.post("/api/solve", data={"demo_id": "nope"}).status_code == 404
    png = (FR / "mojave_az270_alt60.png").read_bytes()
    bad = client.post("/api/solve", files={"file": ("x.png", png)}, data={"mode": "night", "gravity": "[0,0,0]"})
    assert bad.status_code == 422
    assert client.post("/api/solve", data={}).status_code == 400
    assert client.get("/api/last").json()["uid"] == "SKYFIX-1"
    assert client.get("/api/evidence").json()["verify"]["ok"]


def test_device_to_camera_landscape():
    from app import device_to_camera_down
    # landscape-primary (angle 90, device top to the left), camera level: W3C 'up' = +x device -> down must be image-down
    assert np.allclose(device_to_camera_down(9.81, 0, 0, 90), [0, 9.81, 0], atol=1e-9)
    # landscape-secondary (angle 270, device top to the right): up = -x device
    assert np.allclose(device_to_camera_down(-9.81, 0, 0, 270), [0, 9.81, 0], atol=1e-9)


def test_api_validation_and_flip(client):
    png = (FR / "mojave_az270_alt60.png").read_bytes()
    for bad in ({"gravity": "not json"}, {"gravity": "[1,2]"}, {"tilt": "-1"}, {"tilt": "nan"}, {"fov": "0"}):
        r = client.post("/api/solve", files={"file": ("x.png", png)}, data={"mode": "night", **bad})
        assert r.status_code == 422, bad
    # camera level (within +-12 deg of horizon) from device accel -> refuse rather than guess the sign
    r = client.post("/api/solve", files={"file": ("x.png", png)}, data={"mode": "night", "device_accel": "[0,9.81,0]"})
    assert r.status_code == 422
    # iOS-style inverted accel for a camera 60 deg up: W3C up would be (0, 9.81*cos60, -9.81*sin60); iOS reports the negative
    m = json.loads((FR / "mojave_az270_alt60.json").read_text())
    r = client.post("/api/solve", files={"file": ("x.png", png)},
                    data={"mode": "night", "device_accel": json.dumps([0, -9.81 * 0.5, 9.81 * 0.866]), "client_utc": m["utc"].rstrip("Z")}).json()
    assert any("flipped" in n for n in r["notes"])


def test_demo_fix_not_used_as_prior(client):
    import app as A
    client.post("/api/solve", data={"demo_id": "synth:swiss_alps_az030_alt35"})
    assert client.get("/api/last").json()["demo"] is True
    real = [x for x in A.EV.records() if not x.get("demo_id")]
    img = (ROOT / "data/skyline/CH1/cvg/04032011388_01024.png").read_bytes()
    r = client.post("/api/solve", files={"file": ("d.png", img)}, data={"mode": "day", "fov": "56.8"}).json()
    if not real:
        assert "prior_source" not in r and r["result"]["ok"] is False  # no real prior -> refuses, does not use the demo fix


def test_evidence_tail_truncation_detected():
    from evidence import Evidence
    d = pathlib.Path(tempfile.mkdtemp())
    ev = Evidence(d / "e.db", d / "cot")
    for i in range(3):
        ev.append(dict(solver="stars", lat=1.0 * i, lon=2.0, ring_m=1.0, heading_deg=0.0, confidence="x"))
    lines = ev.jsonl.read_text().splitlines()
    ev.jsonl.write_text("\n".join(lines[:-1]) + "\n")  # drop the newest record from the mirror
    assert ev.verify()["ok"] is False


def test_horizon_top_edge_invalid():
    import horizon as H
    sky = np.ones((100, 10), bool); sky[60:] = False; sky[:, 3] = False  # column 3: terrain all the way up
    rows = H.rows_from_sky_mask(sky)
    assert rows[0] == 60 and rows[3] == 0
