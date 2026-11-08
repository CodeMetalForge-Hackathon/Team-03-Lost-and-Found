#!/usr/bin/env bash
# Stop only the services started by run_all.sh (PIDs in run/*.pid). Never kills by pattern.
cd "$(dirname "$0")"
for f in run/*.pid; do
  [ -f "$f" ] || continue; pid=$(cat "$f")
  if kill -0 "$pid" 2>/dev/null; then kill "$pid" && echo "stopped $(basename "$f" .pid) ($pid)"; fi
  rm -f "$f"
done
bash "$(dirname "$0")/telemetry/run.sh" stop 2>/dev/null   # telemetry started by hand via telemetry/run.sh
