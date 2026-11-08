"""
Generate a fake dog run (with GPS) in the same format as the real tracker,
so you can demo indoors.

  python3 make_fake_dog.py                       # default start point, writes dog_log.txt
  python3 make_fake_dog.py --start 42.3550 -71.0656 --bearing 45 --meters 120

The dog starts where the person stands, runs a wandering path, then stops
and goes into FOUND state for ~15 seconds (that spot becomes the target).
"""
import argparse
import math
import random

ap = argparse.ArgumentParser()
ap.add_argument("--start", nargs=2, type=float, default=[42.3550, -71.0656],
                metavar=("LAT", "LON"))
ap.add_argument("--bearing", type=float, default=45, help="general direction the dog runs, degrees")
ap.add_argument("--meters", type=float, default=120, help="straight-line distance to the find")
ap.add_argument("--out", default="dog_log.txt")
ap.add_argument("--seed", type=int, default=7)
a = ap.parse_args()
random.seed(a.seed)

lat0, lon0 = a.start
M_PER_DEG_LAT = 111_320
m_per_deg_lon = 111_320 * math.cos(math.radians(lat0))


def offset(north_m, east_m):
    return lat0 + north_m / M_PER_DEG_LAT, lon0 + east_m / m_per_deg_lon


lines, seq, millis = [], 500, 480_000
north = east = 0.0


def emit(state, motion, lat, lon, fix=1):
    global seq, millis
    lines.append(f"HB,DOG1,{seq},{millis},{motion:.1f},{state},{lat:.6f},{lon:.6f},{fix}")
    seq += 1
    millis += 1000 + random.randint(0, 3)


# a few seconds waiting for GPS, then still at start
for _ in range(3):
    lines.append(f"HB,DOG1,{seq},{millis},{random.uniform(1.5, 2.5):.1f},STILL,,,0")
    seq += 1; millis += 1000
for _ in range(3):
    emit("STILL", random.uniform(1.5, 2.5), *offset(0, 0))

# run: ~3 m/s with wander, heading drifts around the main bearing
dist_left = a.meters
while dist_left > 0:
    hdg = math.radians(a.bearing + random.uniform(-35, 35))
    step = random.uniform(2.5, 3.5)
    north += step * math.cos(hdg)
    east += step * math.sin(hdg)
    dist_left = a.meters - math.hypot(north, east)
    emit("RUN", random.uniform(6.0, 9.0), *offset(north, east))

# dog stops at the person and alerts; small GPS jitter
for _ in range(15):
    jn, je = random.gauss(0, 1.5), random.gauss(0, 1.5)
    emit("FOUND", random.uniform(0.5, 1.5), *offset(north + jn, east + je))

with open(a.out, "w") as f:
    f.write("\n".join(lines) + "\n")

flat, flon = offset(north, east)
print(f"wrote {len(lines)} lines to {a.out}")
print(f"person/start: {lat0:.6f},{lon0:.6f}")
print(f"find spot:    {flat:.6f},{flon:.6f}  (~{math.hypot(north, east):.0f} m away)")
print(f"open the glasses page with:  ?me={lat0:.6f},{lon0:.6f}")
