#!/bin/bash
# Re-run every number in RESULTS.md from the current code. Grids are cached in cache/ (delete to recompute).
cd ~/forge/skyfix; P=~/forge/.venv/bin/python
$P eval_stars.py > results/eval_stars.log 2>&1
$P eval_real.py > results/eval_real.log 2>&1
for d in dev; do for step in 1.0 0.5; do SKYFIX_GRID_STEP=$step $P eval_skyline.py dev rms_detrend auto 2>&1 | grep '^{'; done; done
bash results/run_skyline_test.sh
SKYFIX_NO_WARM=1 $P demo_table.py 2>&1 | grep -v INFO | tail -3
echo ALLDONE
