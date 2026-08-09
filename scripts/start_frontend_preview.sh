#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
FRONTEND_DIR="$REPO_ROOT/frontend"
PID_FILE="$FRONTEND_DIR/frontend-preview.pid"
LOG_FILE="$FRONTEND_DIR/frontend-preview.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Frontend preview already running (PID $(cat "$PID_FILE"))"
  exit 0
fi

if /usr/sbin/lsof -nP -iTCP:8899 -sTCP:LISTEN >/dev/null 2>&1 || /usr/sbin/lsof -nP -iTCP:8877 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Refusing to start: local business port 8899 or GPU worker port 8877 is already listening" >&2
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/dist" ]; then
  echo "Refusing to start: frontend/dist is missing; run npm run build first" >&2
  exit 1
fi

cd "$FRONTEND_DIR"
nohup npm run preview -- --host 127.0.0.1 --port 5173 >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 0.2
if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Frontend preview exited during startup; see $LOG_FILE" >&2
  rm -f "$PID_FILE"
  exit 1
fi
echo "Frontend preview started on http://127.0.0.1:5173 (PID $(cat "$PID_FILE"))"
echo "Log: $LOG_FILE"
