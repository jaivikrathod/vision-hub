#!/usr/bin/env bash
# Start everything for local development: API, analysis worker and frontend.
# Ctrl+C stops all three. Logs go to the terminal (prefixed) and to logs/.
#
#   ./scripts/dev.sh
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PY="$BACKEND/.venv/bin/python"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"

if [[ ! -x "$PY" ]]; then
  echo "Backend virtualenv not found at backend/.venv - see README 'Installation'." >&2
  exit 1
fi
if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "Installing frontend dependencies (first run)…"
  (cd "$FRONTEND" && npm install) || exit 1
fi

pids=()

kill_tree() {  # terminate a process and all of its descendants
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$child"; done
  kill -TERM "$1" 2>/dev/null || true
}

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping…"
  for pid in "${pids[@]}"; do kill_tree "$pid"; done
  wait 2>/dev/null
  echo "Stopped."
}
trap cleanup INT TERM EXIT

run() {  # run <name> <dir> <command...>
  local name="$1" dir="$2"; shift 2
  (cd "$dir" && "$@" 2>&1 | sed -u "s/^/[$name] /" | tee -a "$LOGS/$name.log") &
  pids+=($!)
}

# The API applies database migrations on startup; give it a head start before the worker.
run api "$BACKEND" "$PY" -m uvicorn app.main:app --port 8000
sleep 3
run worker "$BACKEND" "$PY" -m app.workers.analysis_worker
run web "$FRONTEND" npm run dev -- --port 5173

echo
echo "  Vision Hub is starting:"
echo "    App:      http://localhost:5173"
echo "    API docs: http://localhost:8000/docs"
echo "  Press Ctrl+C to stop."
echo
wait
