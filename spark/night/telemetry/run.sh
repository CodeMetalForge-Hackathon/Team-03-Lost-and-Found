#!/usr/bin/env bash
# Runs Local telemetry page on :8160.  bash run.sh [start|stop]
cd "$(dirname "$0")"; N="$(cd .. && pwd)"
if [ "${1:-start}" = "stop" ]; then [ -f run.pid ] && kill "$(cat run.pid)" 2>/dev/null && echo "stopped $(cat run.pid)"; rm -f run.pid; exit 0; fi
if ss -ltn | grep -q ":8160 "; then echo ":8160 already in use"; exit 0; fi
( exec nohup ~/forge/.venv/bin/python server.py 8160 > logs/telemetry_8160.log 2>&1 ) &
echo $! > run.pid; echo "$! telemetry/server.py 8160 $(date +%H:%M) run.sh" >> "$N/PIDS.txt"; echo "telemetry http://$(hostname -I | awk '{print $1}'):8160"
