#!/bin/bash
# Re-run all Phase 2 numbers. Test split: spec baseline (1 km) and 0.5 km grid; SAM2 horizon and oracle GT horizon.
cd ~/forge/skyfix
P=~/forge/.venv/bin/python
for step in 1.0 0.5; do for h in auto gt; do
  SKYFIX_GRID_STEP=$step $P eval_skyline.py test rms_detrend $h 2>&1 | grep '^{'
done; done
SKYFIX_GRID_STEP=1.0 $P eval_skyline.py test ncc auto 2>&1 | grep '^{'
echo DONE
