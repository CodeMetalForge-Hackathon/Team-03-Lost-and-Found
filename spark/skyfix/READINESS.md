# Sky Fix readiness — Sun Nov  8 00:00:32 EST 2026

## Stars
total 69032
drwxrwxr-x 3 darkstar90 darkstar90     4096 Nov  7 23:53 .
drwxrwxr-x 6 darkstar90 darkstar90     4096 Nov  7 23:46 ..
drwxrwxr-x 2 darkstar90 darkstar90     4096 Nov  7 23:51 astrosmartphone
-rw-rw-r-- 1 darkstar90 darkstar90 17358352 Nov  7 23:48 gaia_merged.bin
-rw-rw-r-- 1 darkstar90 darkstar90 53316318 Nov  7 23:53 hip_main.dat
NO phone-FOV database built

## Skyline
total 230500
drwxrwxr-x 3 darkstar90 darkstar90      4096 Nov  7 23:51 .
drwxrwxr-x 6 darkstar90 darkstar90      4096 Nov  7 23:46 ..
drwxrwxr-x 4 darkstar90 darkstar90      4096 Nov  7 23:51 CH1
-rw-rw-r-- 1 darkstar90 darkstar90 236014179 Nov  7 23:47 CH1.tgz
DEM tiles: 19

## Geotagged sky photos
37 photos
 - 360-degree_Panorama_of_the_Southern_Sky.jpg.jpg -24.62747222 -70.40405556 2009-11-09 CC BY 4.0
 - Assy-Turgen_Observatory_against_the_backdrop_of_the_center_o 43.226603 77.872319 2021-07-04 CC BY-SA 4.0
 - Mesmerising_natural_beauty_-_the_milky_way_and_the_desert_at 23.605572 54.750445 2021-05-09 00:44:52 CC BY-SA 4.0
 - Milky_Road_123956845_.jpeg.jpg 50.12346996 -122.92937279 between 12 Septembe CC BY-SA 3.0
 - Milky_Way_Over_Lac_de_Gaube.jpg.jpg 42.833564 -0.138674 2024-07-29 22:26:10 CC BY 4.0
 - The_Milky_Way_in_the_mountains_of_the_Karaganda_region_Kazak 49.840192 76.492855 2025-05-21 03:09:08 CC BY-SA 4.0
 - 2012-01-17_22-11-44-constellations-20f-6d-11o.jpg.jpg 47.64043197 6.86591595 2012-01-17 22:11:44 CC BY 3.0
 - 2012-02-21_21-01-50-orion-78f-12d-11o.jpg.jpg 47.64086932 6.86515152 2012-02-21 21:01:50 CC BY 3.0

## Download report
# Download report — 2026-11-08 00:00:32

Internal free: 2742 GB · SSD free: 53 GB

| id | priority | status | size GB | dest / note |
|---|---|---|---|---|
| mapscore | P1 | CLONED | 0.01 | /home/darkstar90/forge/datasets/mapscore |
| sar-stats-pdfs | P1 | PARTIAL (2/3) |  | /home/darkstar90/forge/datasets/sar_stats |
| sarenv | P1 | CLONED | 0.82 | repo uses git-lfs but git-lfs is not installed (apt install git-lfs; then git lfs pull) |
| cot-samples | P1 | CLONED | 0.0 | /home/darkstar90/forge/datasets/cot/cot-samples |
| cot-validator | P1 | CLONED | 0.0 | /home/darkstar90/forge/datasets/cot/cot-validator |
| osm-ohio | P1 | DOWNLOADED |  | /home/darkstar90/forge/datasets/osm |
| footstep-vibration-8env | P1 | DOWNLOADED |  | /home/darkstar90/forge/datasets/vibration |
| astro-smartphone-dataset | P1 | DOWNLOADED |  | /home/darkstar90/forge/skyfix/data/stars/astrosmartphone |

## Needs attention

- **sar-stats-pdfs** — PARTIAL (2/3) — 

## Notes added at launch (00:03)
- hip_main.dat came from the Harvard CfA VizieR mirror (CDS Strasbourg is unreachable from here; the manifest now points at CfA).
- The phone-FOV tetra3 database is being built RIGHT NOW in tmux session `skydb` (log: skyfix/logs/build_db.log). Output: skyfix/data/stars/phone_fov70_db.npz. Do NOT start a second build; poll for the .npz (check `tail skyfix/logs/build_db.log`). tetra3 is installed editable from skyfix/repos/tetra3-source; hip_main.dat is also at skyfix/repos/tetra3-source/tetra3/hip_main.dat.
- Use the venv python: ~/forge/.venv/bin/python (system python3 has no numpy).
- CH1 is extracted at skyfix/data/skyline/CH1/ (406 images incl. _01024 downsized copies, 204 per-image .txt metadata files under cvg/). Inspect a .txt first to learn the fields.
- 37 geotagged, time-stamped, CC-licensed night-sky photos at skyfix/data/sky_photos/ with index.json (lat, lon, DateTimeOriginal, license, credit). Wikimedia thumbs at 2048 px.
- AstroSmartphoneDataset.zip (1.3 GB) at skyfix/data/stars/astrosmartphone/ (not yet unzipped).
- 19 GLO-30 tiles in skyfix/data/dem (18 Swiss + N41W082 Aukerman).
- git-lfs is not installed, so SAREnv's LFS payload is missing (code is there). Persona map is not your job tonight anyway.
