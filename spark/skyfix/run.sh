#!/usr/bin/env bash
# Sky Fix — one command, offline:  bash ~/forge/skyfix/run.sh      (stop: bash ~/forge/skyfix/run.sh stop)
# :8130 HTTP  (laptop/glasses/demo)   :8131 HTTPS self-signed (phones: DeviceMotion + camera need a secure context)
set -u
cd "$(dirname "$0")"
PY=~/forge/.venv/bin/python
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
mkdir -p logs certs

stop() {
  for f in run/app_http.pid run/app_https.pid; do
    if [ -f "$f" ]; then pid=$(cat "$f")
      kill "$pid" 2>/dev/null && echo "stopped $pid"
      for i in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      rm -f "$f"; fi
  done
}
if [ "${1:-}" = "stop" ]; then stop; exit 0; fi
if [ "${1:-}" = "reset-evidence" ]; then  # archive (never delete) the evidence log + CoT files before a demo
  stop; ts=$(date +%Y%m%d_%H%M%S); mkdir -p evidence/archive/$ts
  mv evidence/skyfix_evidence.* evidence/archive/$ts/ 2>/dev/null; mv cot evidence/archive/$ts/cot 2>/dev/null
  echo "archived to evidence/archive/$ts — now run: bash run.sh"; exit 0; fi
mkdir -p run; stop >/dev/null 2>&1

for port in 8130 8131; do
  if ss -ltn 2>/dev/null | grep -q ":$port "; then echo "port $port is busy — stop the other process first (bash run.sh stop)"; exit 1; fi
done

SKYFIX_PORT=8130 nohup $PY app.py > logs/app_8130.log 2>&1 &
echo $! > run/app_http.pid; echo "$! app.py:8130 (run.sh) $(date +%H:%M)" >> PIDS.txt

if command -v openssl >/dev/null; then
  [ -f certs/key.pem ] || openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=skyfix.local" \
      -keyout certs/key.pem -out certs/cert.pem >/dev/null 2>&1
  nohup $PY -c "import uvicorn,app; uvicorn.run(app.app,host='0.0.0.0',port=8131,ssl_keyfile='certs/key.pem',ssl_certfile='certs/cert.pem')" \
      > logs/app_8131.log 2>&1 &
  echo $! > run/app_https.pid; echo "$! app.py:8131-https (run.sh) $(date +%H:%M)" >> PIDS.txt
fi

for i in $(seq 1 60); do curl -sf localhost:8130/api/health >/dev/null && break; sleep 1; done
curl -sf localhost:8130/api/health >/dev/null || { echo "service did not start — see logs/app_8130.log"; tail -20 logs/app_8130.log; exit 1; }

IPS=$(hostname -I 2>/dev/null)
echo "Sky Fix is up (offline; nothing is transmitted)."
echo "  phone app   http://localhost:8130/"
echo "  glasses HUD http://localhost:8130/?hud=1"
echo "  judge demo  http://localhost:8130/demo"
for ip in $IPS; do case $ip in *:*) ;; *) echo "  LAN/tailnet http://$ip:8130/   phones (motion sensors): https://$ip:8131/  (accept the self-signed cert)";; esac; done
echo "  stop:  bash ~/forge/skyfix/run.sh stop    logs: ~/forge/skyfix/logs/app_8130.log"
