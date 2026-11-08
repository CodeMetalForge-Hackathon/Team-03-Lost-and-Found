"""City-mode solver tests on synthetic geometry (truth camera -> projected taps -> solve). Run: ~/forge/.venv/bin/python -m pytest -q city/tests"""
import json, math, sys
from pathlib import Path
import numpy as np
import pytest
C = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(C))
import resect as R  # noqa: E402

LM = {l["id"]: dict(l, top_asl_m=l["top_asl_m"]) for l in json.loads((C / "data/landmarks.json").read_text())["landmarks"]}
LAT, LON, H = 42.3590, -71.0565, 63.3


def synth(ids, head=75, pitch=4, roll=1.5, W=4032, Hh=3024, h=H):
    f, _, _ = R.focal_px(W, Hh, f35=26); cam = R.Camera(W, Hh, f, None); cam.pitch = math.radians(pitch); cam.roll = math.radians(roll)
    loc = R.Local(LAT, LON); taps = []
    for i in ids:
        q = loc.en(LM[i]["lat"], LM[i]["lon"]); d = np.linalg.norm(q); az = math.atan2(q[0], q[1])
        top = LM[i]["top_asl_m"] if LM[i]["top_asl_m"] is not None else 30
        el = math.atan2(top - h - d * d / (2 * R.R_EARTH) * (1 - R.K_REFR), d)
        x, y = cam.project(R.wrap(az - math.radians(head)), el); taps.append({"id": i, "x": x, "y": y, "top": True})
    hz = [cam.project(math.radians(a), -R.dip(h)) for a in (-25, 25)]
    return taps, hz, f, W, Hh


def test_projection_roundtrip():
    cam = R.Camera(4000, 3000, 2900, [(100, 1500), (3900, 1530)]); cam.set_height(60)
    for az, el in ((0.1, 0.05), (-0.4, -0.02), (0.3, 0.2)):
        x, y = cam.project(az, el); a2, e2 = cam.az_el(x, y)
        assert abs(a2 - az) < 1e-9 and abs(e2 - el) < 1e-9


@pytest.mark.parametrize("ids,head", [(("harbor_towers_2", "custom_house", "harbor_towers_1"), 75),
                                      (("faneuil_cupola", "zakim_south", "bunker_hill"), 0),
                                      (("millennium_tower", "state_street_bank", "one_intl_place"), 160)])
def test_resection_and_height(ids, head):
    taps, hz, f, W, Hh = synth(ids, head=head)
    out = R.solve(taps, LM, W, Hh, f, horizon=hz, ground_fn=lambda a, b: 5.3, ref={"name": "t", "lat": LAT, "lon": LON},
                  height_ids=tuple(i for i in ids if LM[i]["top_asl_m"] is not None)[:1])
    assert out["vs_reference"]["distance_m"] < 0.5
    assert abs(out["heading_deg"] - head % 360) < 0.01 or abs(out["heading_deg"] - head % 360) > 359.99
    if out.get("height"):
        assert abs(out["height"]["primary"]["h_cam_asl_m"] - H) < 0.3


def test_ring_grows_with_angle_error():
    taps, hz, f, W, Hh = synth(("harbor_towers_2", "custom_house", "harbor_towers_1"))
    a = R.solve(taps, LM, W, Hh, f, horizon=hz, angle_err_deg=0.25)["ring_m"]
    b = R.solve(taps, LM, W, Hh, f, horizon=hz, angle_err_deg=0.5)["ring_m"]
    assert 0 < a < b


def test_level_assumed_without_horizon():
    taps, _, f, W, Hh = synth(("harbor_towers_2", "custom_house", "harbor_towers_1"), pitch=0, roll=0)
    out = R.solve(taps, LM, W, Hh, f, horizon=None)
    assert out["camera"]["level_assumed"] and "height" not in out and any("level" in w for w in out["warnings"])


def test_needs_three_distinct():
    taps, hz, f, W, Hh = synth(("custom_house", "custom_house", "harbor_towers_1"))
    with pytest.raises(ValueError):
        R.solve(taps, LM, W, Hh, f, horizon=hz)
