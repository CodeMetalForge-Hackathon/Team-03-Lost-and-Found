#!/usr/bin/env bash
# Start every night-build service and print URLs.
#   ./run_all.sh            fresh mission: archive the previous evidence chain, CoT, inbox, clues; start services
#   ./run_all.sh --keep     keep the current chain/clues (e.g. after a crash)
# Ports 8140-8149 only. PIDs go to run/*.pid and PIDS.txt. stop_all.sh kills only those PIDs.
set -uo pipefail
cd "$(dirname "$0")"; N="$(pwd)"; PY=~/forge/.venv/bin/python
mkdir -p run logs evidence/archive inbox
KEEP=0; [ "${1:-}" = "--keep" ] && KEEP=1
if [ $KEEP -eq 0 ]; then
  TS=$(date +%Y%m%d_%H%M%S); A="evidence/archive/$TS"; mkdir -p "$A"
  [ -f evidence/chain.jsonl ] && mv evidence/chain.jsonl "$A/"
  [ -d evidence/cot ] && mv evidence/cot "$A/"
  [ -d inbox/processed ] && mv inbox/processed "$A/inbox_processed"
  [ -d inbox/rejected ] && mv inbox/rejected "$A/inbox_rejected"
  ls inbox/*.json >/dev/null 2>&1 && mkdir -p "$A/inbox_pending" && mv inbox/*.json "$A/inbox_pending/"
  [ -f map/clues.json ] && mv map/clues.json "$A/"
  [ -d map/clue_photos ] && mv map/clue_photos "$A/"
  rm -f map/state.json
  echo "previous evidence archived to $A (nothing deleted)"
fi
start () {  # name port dir script
  local name=$1 port=$2 dir=$3 script=$4
  if ss -ltn | grep -q ":$port "; then echo "  $name: port $port already in use, not starting (./stop_all.sh first)"; return; fi
  ( cd "$N/$dir" && exec nohup $PY "$script" "$port" > "$N/logs/${name}_$port.log" 2>&1 ) &
  local pid=$!; echo $pid > "run/$name.pid"; echo "$pid $dir/$script $port $(date +%H:%M) run_all" >> PIDS.txt
}
start fusion 8140 fusion fuse.py
start dog    8141 dog    serve.py
start perch  8142 perch  serve.py
start map    8143 map    serve.py
for i in $(seq 1 40); do
  ok=0; for p in 8140 8141 8142 8143; do curl -s -m 1 "localhost:$p/health" >/dev/null && ok=$((ok+1)); done
  [ $ok -eq 4 ] && break; sleep 0.5
done
H=$(hostname -I | awk '{print $1}')
echo
echo "  fusion console + evidence chain + AAR   http://$H:8140"
echo "  dog stand-in replay                     http://$H:8141"
echo "  perch and listen                        http://$H:8142"
echo "  persona search map + clue engine        http://$H:8143"
echo "  ($ok/4 services answering /health)"
echo "  tap three live (needs a USB/contact mic):  $PY tap3/live.py --x 5.3 --y 3.85"
echo "  demo driver (dog replay → inbox):          $PY scenario.py"
