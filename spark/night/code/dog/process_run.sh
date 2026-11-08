#!/usr/bin/env bash
# Process one dog run folder (DOG_HANDOFF format): track -> sync -> layers. Usage: process_run.sh RUN_DIR [--clap-frame N] [--emit]
set -euo pipefail
PY=~/forge/.venv/bin/python; D="$(cd "$(dirname "$0")" && pwd)"; RUN="$1"; shift || true
CLAP=(); EMIT=()
while [ $# -gt 0 ]; do case "$1" in --clap-frame) CLAP=(--clap-frame "$2"); shift 2;; --emit) EMIT=(--emit); shift;; *) shift;; esac; done
$PY "$D/track_overhead.py" "$RUN"
$PY "$D/sync.py" "$RUN" "${CLAP[@]}"
$PY "$D/layers.py" "$RUN" "${EMIT[@]}"
echo "done: $RUN  (open http://localhost:8141 and pick the run)"
