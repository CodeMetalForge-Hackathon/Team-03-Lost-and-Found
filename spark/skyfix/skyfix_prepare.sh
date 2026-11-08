#!/usr/bin/env bash
# Sky Fix prep on the Spark: download, extract, install solvers, build the phone-FOV star database,
# fetch geotagged night-sky photos from Wikimedia Commons, write a readiness report.
# Run inside tmux:   bash ~/forge/skyfix_prepare.sh 2>&1 | tee ~/forge/skyfix/logs/prepare.log
set -u
cd "$HOME/forge" || exit 1
mkdir -p skyfix/{data/stars,data/skyline,data/dem,data/sky_photos,repos,logs}
export PIP_BREAK_SYSTEM_PACKAGES=1
PY=python3; [ -x "$HOME/forge/.venv/bin/python" ] && PY="$HOME/forge/.venv/bin/python"

echo "== 1. downloads (P0 first, then P1) =="
$PY download_all.py --manifest manifest_skyfix.yaml --priority P0 2>&1 | tail -20
$PY download_all.py --manifest manifest_skyfix.yaml --priority P1 --skip-pip 2>&1 | tail -20 &
P1_PID=$!

echo "== 2. extract CH1 =="
if [ -f skyfix/data/skyline/CH1.tgz ] && [ ! -d skyfix/data/skyline/CH1 ]; then
  mkdir -p skyfix/data/skyline/CH1 && tar -xzf skyfix/data/skyline/CH1.tgz -C skyfix/data/skyline/CH1 && echo "CH1 extracted: $(find skyfix/data/skyline/CH1 -type f | wc -l) files"
fi

echo "== 3. hip_main.dat fallback paths =="
HIP=skyfix/data/stars/hip_main.dat
if [ ! -s "$HIP" ] || [ "$(stat -c%s "$HIP")" -lt 40000000 ]; then
  for u in "https://cdsarc.cds.unistra.fr/ftp/I/239/hip_main.dat.gz" "https://cdsarc.u-strasbg.fr/ftp/cats/I/239/hip_main.dat" "https://cdsarc.u-strasbg.fr/ftp/cats/I/239/hip_main.dat.gz"; do
    echo "trying $u"; curl -fsSL -o skyfix/data/stars/hip_tmp "$u" || continue
    if file skyfix/data/stars/hip_tmp | grep -qi gzip; then gunzip -c skyfix/data/stars/hip_tmp > "$HIP"; else mv skyfix/data/stars/hip_tmp "$HIP"; fi
    rm -f skyfix/data/stars/hip_tmp; [ "$(stat -c%s "$HIP")" -gt 40000000 ] && break
  done
fi
ls -la "$HIP" || echo "WARNING: hip_main.dat missing"

echo "== 4. solvers =="
$PY -m pip install -q -e skyfix/repos/tetra3-source 2>&1 | tail -2 || $PY -m pip install -q "git+https://github.com/esa/tetra3.git" 2>&1 | tail -2
$PY -m pip install -q cedar-solve 2>&1 | tail -2 || echo "cedar-solve pip install failed (optional)"
$PY -c "import tetra3, sys; print('tetra3 OK', getattr(tetra3,'__version__','?'))" || echo "WARNING: tetra3 import failed"

echo "== 5. build phone-FOV star database (max_fov 70, min_fov 20) =="
$PY - <<'EOF'
import os, shutil, pathlib, sys
try:
    import tetra3
except Exception as e:
    print("tetra3 missing:", e); sys.exit(0)
hip = pathlib.Path("skyfix/data/stars/hip_main.dat")
if not hip.exists() or hip.stat().st_size < 40_000_000:
    print("no hip_main.dat; skip db build"); sys.exit(0)
# tetra3 looks for the catalog inside its package data dir
pkg = pathlib.Path(tetra3.__file__).parent
data_dir = pkg / "data"; data_dir.mkdir(exist_ok=True)
tgt = data_dir / "hip_main.dat"
if not tgt.exists(): shutil.copy(hip, tgt)
t3 = tetra3.Tetra3(load_database=None)
out = pathlib.Path("skyfix/data/stars/phone_fov70_db")
try:
    t3.generate_database(max_fov=70, min_fov=20, star_catalog="hip_main", save_as=str(out), star_max_magnitude=7)
    print("database saved:", out)
except TypeError:
    t3.generate_database(max_fov=70, star_catalog="hip_main", save_as=str(out))
    print("database saved (legacy signature):", out)
except Exception as e:
    print("generate_database failed:", e)
EOF

echo "== 6. geotagged night-sky photos from Wikimedia Commons (CC licensed, with coordinates + capture time) =="
$PY - <<'EOF'
import json, os, pathlib, requests, time, re
out = pathlib.Path("skyfix/data/sky_photos"); out.mkdir(parents=True, exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = "RescueBase-SkyFix/0.1 (hackathon research)"
API = "https://commons.wikimedia.org/w/api.php"
queries = ["Milky Way night sky landscape", "Orion constellation night photograph", "night sky stars mountains", "Big Dipper night sky", "starry sky horizon"]
rows, seen = [], set()
for q in queries:
    try:
        r = S.get(API, params=dict(action="query", generator="search", gsrsearch=f"filetype:bitmap {q}", gsrnamespace=6, gsrlimit=40,
                                  prop="imageinfo|coordinates", iiprop="url|extmetadata|size", iiurlwidth=2048, format="json"), timeout=60).json()
    except Exception as e:
        print("search failed", q, e); continue
    for p in r.get("query", {}).get("pages", {}).values():
        if "coordinates" not in p: continue           # need a geotag
        ii = p["imageinfo"][0]; md = ii.get("extmetadata", {})
        lic = md.get("LicenseShortName", {}).get("value", "")
        dt = md.get("DateTimeOriginal", {}).get("value", "")
        if not re.search(r"\d{4}-\d{2}-\d{2}", dt) or p["title"] in seen: continue
        if not any(k in lic for k in ("CC BY", "CC0", "Public domain")): continue
        seen.add(p["title"]); c = p["coordinates"][0]
        fn = out / (re.sub(r"[^A-Za-z0-9._-]+", "_", p["title"].replace("File:", ""))[:120] + ".jpg")
        try:
            img = S.get(ii.get("thumburl") or ii["url"], timeout=120); fn.write_bytes(img.content)
        except Exception as e:
            print("download failed", p["title"], e); continue
        rows.append(dict(file=fn.name, title=p["title"], lat=c["lat"], lon=c["lon"], datetime_original=dt, license=lic,
                         artist=re.sub("<[^>]+>", "", md.get("Artist", {}).get("value", "")), source=ii.get("descriptionurl")))
        time.sleep(0.3)
        if len(rows) >= 40: break
    if len(rows) >= 40: break
json.dump(rows, open(out / "index.json", "w"), indent=1)
print(f"saved {len(rows)} geotagged, time-stamped, CC-licensed night-sky photos to {out}/ (index.json has lat/lon/time/license/credit)")
EOF

echo "== 7. CH1 index (what did we get?) =="
$PY - <<'EOF'
import pathlib, glob
root = pathlib.Path("skyfix/data/skyline/CH1")
files = sorted(root.rglob("*")) if root.exists() else []
imgs = [f for f in files if f.suffix.lower() in (".jpg", ".jpeg", ".png")]
meta = [f for f in files if f.suffix.lower() in (".txt", ".csv", ".xml", ".json", ".mat")]
print(f"CH1: {len(imgs)} images, {len(meta)} metadata files")
for f in meta[:10]: print("  meta:", f.relative_to(root))
EOF

wait $P1_PID 2>/dev/null
echo "== 8. report =="
{
  echo "# Sky Fix readiness — $(date)"
  echo; echo "## Stars"; ls -la skyfix/data/stars 2>/dev/null; ls -la skyfix/data/stars/phone_fov70_db* 2>/dev/null || echo "NO phone-FOV database built"
  echo; echo "## Skyline"; ls -la skyfix/data/skyline 2>/dev/null; echo "DEM tiles: $(ls skyfix/data/dem/*.tif 2>/dev/null | wc -l)"
  echo; echo "## Geotagged sky photos"; $PY -c "import json;d=json.load(open('skyfix/data/sky_photos/index.json'));print(len(d),'photos');[print(' -',r['file'][:60],r['lat'],r['lon'],r['datetime_original'][:19],r['license']) for r in d[:8]]" 2>/dev/null || echo "none"
  echo; echo "## Download report"; tail -40 logs/download_report.md 2>/dev/null
} > skyfix/READINESS.md
cat skyfix/READINESS.md
echo "DONE. Next: tmux new -s skyfix; bash ~/forge/skyfix_run_claude.sh"
