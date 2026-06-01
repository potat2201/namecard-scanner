#!/usr/bin/env bash
# Shared helpers for dev scripts.

load_env() {
  local root="$1"
  if [[ -f "$root/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$root/.env"
    set +a
  fi
}

require_port_free() {
  local port="$1"
  local label="${2:-process}"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Error: port $port is already in use (needed for $label):" >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
    echo "" >&2
    echo "Free it with: kill \$(lsof -t -iTCP:$port -sTCP:LISTEN)" >&2
    exit 1
  fi
}
