#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "YOUR_MAC_IP")"

echo "Starting backend on 0.0.0.0:8000..."
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
source .venv/bin/activate
export LAN_EXPOSE=true
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACK_PID=$!

echo "Starting frontend on 0.0.0.0:5173..."
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
LAN_EXPOSE=true npm run dev:lan &
FRONT_PID=$!

echo ""
echo "Open from other devices on your home network:"
echo "  http://${LAN_IP}:5173"
echo ""
echo "Ensure Mac firewall allows incoming connections for Node/Python if prompted."
echo ""

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT
wait
