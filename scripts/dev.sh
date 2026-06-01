#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/lib.sh"

load_env "$ROOT"

FRONTEND_PORT="${PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

require_port_free "$BACKEND_PORT" "backend API"
require_port_free "$FRONTEND_PORT" "frontend (Vite)"

echo "Starting backend on :${BACKEND_PORT}..."
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
source .venv/bin/activate
uvicorn app.main:app --reload --port "$BACKEND_PORT" &
BACK_PID=$!

echo "Starting frontend on localhost:${FRONTEND_PORT}..."
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
export PORT="$FRONTEND_PORT"
if [[ "${LAN_EXPOSE:-false}" == "true" ]]; then
  export LAN_EXPOSE=true
  npm run dev:lan &
else
  npm run dev &
fi
FRONT_PID=$!

echo ""
echo "Open: http://localhost:${FRONTEND_PORT}/"
echo ""

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT
wait
