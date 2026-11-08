#!/usr/bin/env bash
# Zoom to Earth: start the zoom screen server (:8150) and print every URL of the demo.
#   bash ~/forge/zoom/run.sh          start :8150 if not running (night shell :8140-8143 is started by night/run_all.sh)
#   bash ~/forge/zoom/run.sh reset    also forget which AIR/WATER events were already emitted (use after night/run_all.sh)
set -uo pipefail
Z=$HOME/forge/zoom; PY=$HOME/forge/.venv/bin/python; cd "$Z"
if ! ss -ltn | grep -q ":8150 "; then
  ( cd "$Z" && exec nohup $PY serve.py 8150 > "$Z/logs/serve8150.log" 2>&1 ) &
  echo "$! zoom/serve.py 8150 $(date +%H:%M) run.sh" >> "$Z/PIDS.txt"
  for i in $(seq 1 20); do curl -s -m 1 localhost:8150/api/scenes >/dev/null && break; sleep 0.5; done
fi
[ "${1:-}" = "reset" ] && curl -s -X POST "localhost:8150/api/emit/reset" >/dev/null && echo "emitted-event memory reset"
for p in 8140 8141 8142 8143; do curl -s -m 1 "localhost:$p/health" >/dev/null || echo "  WARNING: night service on :$p is down -> cd ~/forge/night && ./run_all.sh"; done
H=$(hostname -I | awk '{print $1}')
echo
echo "  Sky Fix (phone)                            http://$H:8130   (bash ~/forge/skyfix/run.sh)"
echo "  AIR: NOAA ortho + detector + map forming   http://$H:8150/air"
echo "  WATER: sonar mosaic + call-outs            http://$H:8150/water"
echo "  COP (persona map, layers, NBA, replays)    http://$H:8143"
echo "  dog replay                                 http://$H:8141"
echo "  fusion console + chain + AAR               http://$H:8140"
echo
echo "  dog bark replay (optional, terminal):  $PY $Z/land/bark_live.py --wav \"$Z/land/dog03/03 Play session recordings/P-03/P-03-S-P_1.wav\" --offset_s 50 --dur_s 40 --speed 2"
