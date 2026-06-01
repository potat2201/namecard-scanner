#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/lib.sh"

export LAN_EXPOSE=true
load_env "$ROOT"

FRONTEND_PORT="${PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "YOUR_MAC_IP")"

require_port_free "$BACKEND_PORT" "backend API"
require_port_free "$FRONTEND_PORT" "frontend (Vite)"

echo "Starting backend on 0.0.0.0:${BACKEND_PORT}..."
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT" &
BACK_PID=$!

echo "Starting frontend on 0.0.0.0:${FRONTEND_PORT}..."
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
export PORT="$FRONTEND_PORT"
LAN_EXPOSE=true npm run dev:lan &
FRONT_PID=$!

echo ""
echo "Open from this Mac:     http://localhost:${FRONTEND_PORT}/"
echo "Open from other devices: http://${LAN_IP}:${FRONTEND_PORT}/"
echo ""
echo "Add to .env if needed: CORS_ORIGINS=http://localhost:${FRONTEND_PORT},http://${LAN_IP}:${FRONTEND_PORT}"
echo "Ensure Mac firewall allows Node/Python if prompted."
echo ""

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT
wait
