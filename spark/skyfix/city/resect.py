"""Sky Fix city mode: three-point resection (Snellius–Pothenot) from tapped landmarks in one photo. No compass, no GPS.

Pipeline (all angles in degrees at the API, radians inside):
 1. Lens: f_px (focal length in pixels) from EXIF FocalLengthIn35mmFilm (f35/36 mm x long side px), else FocalLength mm and a
    sensor width, else the 69 deg HFOV fallback of an iPhone main lens.
 2. Camera attitude: roll from two taps on the sea horizon; pitch from the horizon's height, which sits at -dip(h) below
    true horizontal (dip with standard refraction k = 0.13). No horizon taps -> level camera assumed (flagged).
 3. Each tapped pixel -> azimuth offset phi_i from the optical axis and true elevation e_i (pinhole, roll/pitch removed).
 4. Resection: the two directed angles alpha = phi_B - phi_A, beta = phi_C - phi_B fix the position. Closed form by the
    classic two-circle construction (each angle puts P on a circle through two landmarks; both circles pass through B, so P is
    B reflected across the line of centres), then a Gauss-Newton polish on (E, N, heading) that also accepts > 3 landmarks.
 5. Confidence ring: re-solve with each angle perturbed by -0.5, 0, +0.5 deg (9 combinations); ring = max displacement.
 6. Heading = bearing(P -> landmark) - phi (mean over landmarks). Sun azimuth at the EXIF time from astropy, as a sanity check.
 7. Height: for a landmark tapped at its top, h_cam = top_asl - d * tan(e_top) - curvature; floor at 12 ft/floor.
"""
from __future__ import annotations
import math
import numpy as np

R_EARTH = 6371008.8
K_REFR = 0.13
FT12 = 12 * 0.3048


# ---------------- geometry ----------------
class Local:
    """Equirectangular east/north metres about (lat0, lon0); error < 1 cm over a few km."""
    def __init__(self, lat0, lon0):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = math.radians(1) * R_EARTH * math.cos(math.radians(lat0)); self.ky = math.radians(1) * R_EARTH

    def en(self, lat, lon):
        return np.array([(lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky])

    def ll(self, e, n):
        return self.lat0 + n / self.ky, self.lon0 + e / self.kx


def bearing(p, q):
    """Bearing (rad, clockwise from north) from p to q in local EN."""
    d = q - p; return math.atan2(d[0], d[1])


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2); dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def dip(h):
    """Sea-horizon dip below true horizontal (rad) for eye height h metres, refraction k."""
    return math.sqrt(2 * max(h, 0.0) * (1 - K_REFR) / R_EARTH)


# ---------------- lens ----------------
def focal_px(W, H, f35=None, f_mm=None, sensor_w_mm=None, hfov_fallback=69.0):
    """Focal length in pixels for the long image side. Returns (f_px, how, hfov_long_deg)."""
    L = max(W, H)
    if f35:
        f = f35 / 36.0 * L; how = f"EXIF FocalLengthIn35mmFilm {f35} mm (36 mm long-side convention)"
    elif f_mm and sensor_w_mm:
        f = f_mm / sensor_w_mm * L; how = f"EXIF FocalLength {f_mm} mm / sensor width {sensor_w_mm} mm"
    else:
        f = (L / 2) / math.tan(math.radians(hfov_fallback) / 2); how = f"fallback HFOV {hfov_fallback} deg (iPhone main lens)"
    return f, how, math.degrees(2 * math.atan(L / 2 / f))


# ---------------- camera model ----------------
class Camera:
    """Pinhole with roll (from horizon taps) and pitch (from horizon height). Image coords: x right, y down."""
    def __init__(self, W, H, f, horizon=None, h_guess=50.0):
        self.W, self.H, self.f = W, H, f; self.cx, self.cy = W / 2, H / 2
        self.roll = 0.0; self.pitch = 0.0; self.horizon = horizon; self.level_assumed = horizon is None
        if horizon:
            (x1, y1), (x2, y2) = horizon
            self.roll = math.atan2(y2 - y1, x2 - x1) if abs(x2 - x1) > 1e-6 else 0.0
        self.set_height(h_guess)

    def uv(self, x, y):
        """Pixel -> (u right, v up) in a roll-corrected frame, relative to the principal point."""
        dx, dy = x - self.cx, y - self.cy
        c, s = math.cos(-self.roll), math.sin(-self.roll)
        return dx * c - dy * s, -(dx * s + dy * c)

    def set_height(self, h):
        """Pitch so that the tapped sea horizon lies at elevation -dip(h)."""
        self.h = h
        if not self.horizon:
            self.pitch = 0.0; return
        target = -dip(h); ps = []
        for x, y in self.horizon:                  # a constant-elevation line projects as a curve: solve pitch per tap, average
            u, v = self.uv(x, y); p = 0.0
            for _ in range(30):                    # solve elevation(u, v; p) = target
                p += target - self._elev(u, v, p)
            ps.append(p)
        self.pitch = float(np.mean(ps))

    def _dir(self, u, v, p):
        return u, v * math.cos(p) + self.f * math.sin(p), self.f * math.cos(p) - v * math.sin(p)

    def _elev(self, u, v, p):
        x, y, z = self._dir(u, v, p); return math.atan2(y, math.hypot(x, z))

    def project(self, az, el):
        """Inverse of az_el: (azimuth offset, true elevation) rad -> pixel (x, y), or None if behind the camera."""
        X, Y, Z = math.sin(az) * math.cos(el), math.sin(el), math.cos(az) * math.cos(el)
        p = self.pitch; v1 = Y * math.cos(p) - Z * math.sin(p); w = Y * math.sin(p) + Z * math.cos(p)
        if w <= 1e-6:
            return None
        u, v = self.f * X / w, self.f * v1 / w
        c, s = math.cos(self.roll), math.sin(self.roll); dx, dy = u, -v
        return self.cx + dx * c - dy * s, self.cy + dx * s + dy * c

    def az_el(self, x, y):
        """(azimuth offset from the optical axis, clockwise +; true elevation) in rad."""
        u, v = self.uv(x, y); X, Y, Z = self._dir(u, v, self.pitch)
        return math.atan2(X, Z), math.atan2(Y, math.hypot(X, Z))


# ---------------- resection ----------------
def _circle_center(A, B, ang):
    """Centres of the two circles through A, B on which chord AB subtends |ang|."""
    d = B - A; L = np.linalg.norm(d); M = (A + B) / 2; nrm = np.array([-d[1], d[0]]) / L
    t = L / (2 * math.tan(abs(ang)))
    return [M + nrm * t, M - nrm * t]


def _reflect(B, O1, O2):
    d = O2 - O1; dd = d @ d
    if dd < 1e-9:
        return None
    t = ((B - O1) @ d) / dd; F = O1 + t * d
    return 2 * F - B


def _pred_dirs(P, pts):
    return [bearing(P, q) for q in pts]


def resect3(pts, phi):
    """Closed-form Snellius–Pothenot for 3 landmarks (local EN arrays) and azimuth offsets phi (rad). Returns P or None."""
    A, B, C = pts; alpha, beta = wrap(phi[1] - phi[0]), wrap(phi[2] - phi[1])
    best, bres = None, 1e9
    for O1 in _circle_center(A, B, alpha):
        for O2 in _circle_center(B, C, beta):
            P = _reflect(B, O1, O2)
            if P is None or np.linalg.norm(P - B) < 1.0:
                continue
            b = _pred_dirs(P, pts)
            res = abs(wrap(b[1] - b[0] - alpha)) + abs(wrap(b[2] - b[1] - beta))
            if res < bres:
                best, bres = P, res
    return best if bres < 1e-6 else (best if best is not None and bres < math.radians(0.5) else None)


def polish(P, pts, phi, iters=30):
    """Gauss-Newton on (E, N, heading) minimising bearing residuals; works for >= 3 landmarks."""
    th = float(np.mean([wrap(bearing(P, q) - f) for q, f in zip(pts, phi)]))
    x = np.array([P[0], P[1], th])
    for _ in range(iters):
        r, J = [], []
        for q, f in zip(pts, phi):
            d = q - x[:2]; r2 = d @ d
            r.append(wrap(math.atan2(d[0], d[1]) - (x[2] + f)))
            J.append([-d[1] / r2, d[0] / r2, -1.0])     # d(bearing)/dE, d/dN, d/dtheta
        r, J = np.array(r), np.array(J)
        dx = np.linalg.lstsq(J, -r, rcond=None)[0]; x += dx
        if np.abs(dx[:2]).max() < 1e-4:
            break
    r = np.array([wrap(bearing(x[:2], q) - (x[2] + f)) for q, f in zip(pts, phi)])
    return x[:2], wrap(x[2]), r


def solve_position(pts, phi):
    P = resect3(pts[:3], phi[:3])
    if P is None:
        return None
    return polish(P, pts, phi)


def danger(pts, P):
    """Distance of P from the circle through the first three landmarks, as a fraction of its radius (0 = singular)."""
    A, B, C = pts[:3]
    a = np.array([[2 * (B - A)[0], 2 * (B - A)[1]], [2 * (C - A)[0], 2 * (C - A)[1]]])
    b = np.array([B @ B - A @ A, C @ C - A @ A])
    try:
        O = np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        return None
    R = np.linalg.norm(A - O); return abs(np.linalg.norm(P - O) - R) / R


# ---------------- sun ----------------
def sun_azalt(lat, lon, when_iso):
    from astropy.coordinates import EarthLocation, AltAz, get_sun
    from astropy.time import Time
    import astropy.units as u
    from datetime import datetime, timezone
    t = Time(datetime.fromisoformat(when_iso).astimezone(timezone.utc).replace(tzinfo=None), scale="utc"); loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m)
    s = get_sun(t).transform_to(AltAz(obstime=t, location=loc))
    return float(s.az.deg), float(s.alt.deg)


# ---------------- top level ----------------
def solve(taps, landmarks, W, H, f_px, horizon=None, when_iso=None, ground_fn=None, ref=None, angle_err_deg=0.5,
          height_ids=("custom_house",), ft_per_floor=13.7):
    """taps: [{id, x, y, top: bool}] (>= 3 with distinct ids); landmarks: {id: {...lat, lon, top_asl_m}}.
    Returns a dict ready for JSON."""
    LM = landmarks; ids = [t["id"] for t in taps]
    if len(taps) < 3 or len(set(ids)) < 3:
        raise ValueError("tap at least 3 different landmarks")
    lat0 = float(np.mean([LM[i]["lat"] for i in ids])); lon0 = float(np.mean([LM[i]["lon"] for i in ids]))
    loc = Local(lat0, lon0); pts = [loc.en(LM[i]["lat"], LM[i]["lon"]) for i in ids]
    cam = Camera(W, H, f_px, horizon, 50.0)
    out = {"warnings": []}
    h = 50.0
    for it in range(6):                           # pitch depends on eye height through the horizon dip; iterate
        cam.set_height(h)
        ae = [cam.az_el(t["x"], t["y"]) for t in taps]; phi = [a for a, _ in ae]
        sol = solve_position(pts, phi)
        if sol is None:
            raise ValueError("no resection solution (landmarks nearly collinear with the camera, or angles inconsistent)")
        P, th, res = sol
        hs = []
        for t, (_, el), q in zip(taps, ae, pts):
            L = LM[t["id"]]
            if t.get("top", True) and L.get("top_asl_m") is not None and horizon:
                d = float(np.linalg.norm(q - P)); curv = d * d / (2 * R_EARTH) * (1 - K_REFR)
                hs.append({"id": t["id"], "name": L["name"], "dist_m": round(d, 1), "elev_deg": round(math.degrees(el), 3),
                           "h_cam_asl_m": L["top_asl_m"] - d * math.tan(el) - curv})
        prim = next((x for x in hs if x["id"] in height_ids), hs[0] if hs else None)
        if prim is None or abs(prim["h_cam_asl_m"] - h) < 0.05:
            break
        h = max(prim["h_cam_asl_m"], 1.0)
    lat, lon = loc.ll(*P)
    out["_cam"] = cam
    alpha, beta = wrap(phi[1] - phi[0]), wrap(phi[2] - phi[1])
    # ring: perturb both angles by -e, 0, +e
    e = math.radians(angle_err_deg); disp = []
    for da in (-e, 0, e):
        for db in (-e, 0, e):
            ph = [phi[0], phi[1] + da, phi[2] + da + db] + list(phi[3:])
            s = solve_position(pts, ph)
            disp.append(float(np.linalg.norm(s[0] - P)) if s is not None else float("inf"))
    ring = max(disp)
    dg = danger(pts, P)
    if dg is not None and dg < 0.15:
        out["warnings"].append(f"camera is near the circle through the three landmarks ({dg:.0%} of its radius): resection is ill-conditioned; pick a landmark off that circle")
    if cam.level_assumed:
        out["warnings"].append("no sea-horizon taps: camera assumed level (roll = pitch = 0); bearings degrade with tilt and no height is computed")
    heading = math.degrees(th) % 360
    out.update(lat=lat, lon=lon, ring_m=round(ring, 1), ring_angle_err_deg=angle_err_deg,
               ring_grid_m=[round(x, 1) for x in disp], heading_deg=round(heading, 2),
               angles_deg={"alpha_AB": round(math.degrees(alpha), 3), "beta_BC": round(math.degrees(beta), 3)},
               residuals_deg=[round(math.degrees(r), 4) for r in res], danger_circle_frac=None if dg is None else round(dg, 3),
               camera={"f_px": round(f_px, 1), "roll_deg": round(math.degrees(cam.roll), 3), "pitch_deg": round(math.degrees(cam.pitch), 3),
                       "level_assumed": cam.level_assumed},
               landmarks=[{"id": t["id"], "name": LM[t["id"]]["name"], "phi_deg": round(math.degrees(p), 3),
                           "elev_deg": round(math.degrees(el), 3), "dist_m": round(float(np.linalg.norm(q - P)), 1),
                           "bearing_deg": round(math.degrees(bearing(P, q)) % 360, 2)} for t, p, (_, el), q in zip(taps, phi, ae, pts)])
    # height / floor
    if hs:
        g = None
        if ground_fn:
            try:
                g = ground_fn(lat, lon); gsrc = "USGS 3DEP 1 m (EPQS)"
            except Exception:
                g = None
        if g is None:
            g, gsrc = 5.0, "assumed 5 m (EPQS unavailable)"
        for x in hs:
            x["h_cam_asl_m"] = round(x["h_cam_asl_m"], 1); x["h_above_ground_m"] = round(x["h_cam_asl_m"] - g, 1)
            x["floor_est"] = round(x["h_above_ground_m"] / (ft_per_floor * 0.3048), 1)
        out["height"] = {"primary": prim, "all": hs, "ground_m": round(g, 1), "ground_source": gsrc,
                         "ft_per_floor": ft_per_floor,
                         "floor_rule": f"floor = camera height above street / ({ft_per_floor} ft per floor)", "dip_deg": round(math.degrees(dip(h)), 3)}
    # sun sanity
    if when_iso:
        try:
            az, alt = sun_azalt(lat, lon, when_iso); rel = (az - heading + 540) % 360 - 180
            hfov = math.degrees(2 * math.atan(W / 2 / f_px))
            inframe = abs(rel) < hfov / 2 and alt > 0
            x_px = W / 2 + f_px * math.tan(math.radians(rel)) if abs(rel) < 89 else None
            out["sun"] = {"time": when_iso, "azimuth_deg": round(az, 2), "altitude_deg": round(alt, 2),
                          "relative_to_heading_deg": round(rel, 2), "image_hfov_deg": round(hfov, 1), "in_frame": bool(inframe),
                          "expected_x_px": round(x_px) if (inframe and x_px is not None) else None,
                          "check": ("sun should be IN the frame near x=%d px; is it (or its glare) there?" % x_px) if inframe else
                                   ("sun is %.0f deg %s of the view direction (alt %.0f deg): it should be out of frame; shadows and lit faces should agree"
                                    % (abs(rel), "right" if rel > 0 else "left", alt))}
        except Exception as ex:
            out["sun"] = {"error": f"{type(ex).__name__}: {ex}"}
    if ref:
        out["vs_reference"] = {"name": ref["name"], "lat": ref["lat"], "lon": ref["lon"],
                               "distance_m": round(haversine(lat, lon, ref["lat"], ref["lon"]), 1),
                               "inside_ring": haversine(lat, lon, ref["lat"], ref["lon"]) <= ring}
    return out
