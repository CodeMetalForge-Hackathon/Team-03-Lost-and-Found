#!/bin/bash
# One-window demo launcher: server + tunnel + dog replay.
#   chmod +x start.sh     (once)
#   ./start.sh            (real dog on serial:  ./start.sh /dev/tty.usbmodem1101)
# Ctrl+C stops everything.

cd "$(dirname "$0")"
ME="42.355000,-71.065600"
LOG=".tunnel.log"

cleanup() { echo; echo "Stopping..."; kill $SERVER_PID $TUNNEL_PID 2>/dev/null; exit 0; }
trap cleanup INT TERM

# 1) server
python3 server.py > .server.log 2>&1 &
SERVER_PID=$!
sleep 1
if ! kill -0 $SERVER_PID 2>/dev/null; then
  echo "server.py failed to start:"; cat .server.log; exit 1
fi

# 2) tunnel (wait until it prints the public URL)
cloudflared tunnel --url http://127.0.0.1:8000 > "$LOG" 2>&1 &
TUNNEL_PID=$!
URL=""
for i in $(seq 1 30); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | head -1)
  [ -n "$URL" ] && break
  sleep 1
done
if [ -z "$URL" ]; then
  echo "Tunnel did not start. Last lines:"; tail -5 "$LOG"; cleanup
fi

echo "=============================================="
echo " Glasses URL (paste into Meta AI app if changed):"
echo "   $URL/?me=$ME"
echo "=============================================="
echo "$URL/?me=$ME" | pbcopy 2>/dev/null && echo " (copied to clipboard)"

# 3) data
if [ -n "$1" ]; then
  echo "Reading real dog from $1 ..."
  python3 dog_bridge.py --port "$1"
else
  while true; do
    echo
    read -r -p "Press Enter to play the dog run (Ctrl+C to quit) "
    python3 dog_bridge.py --file dog_log.txt --replay-delay 1 | tail -1
    echo "Dog run finished. Target stays locked on the glasses."
  done
fi
cleanup
