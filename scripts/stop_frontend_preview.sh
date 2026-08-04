#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
FRONTEND_DIR="$REPO_ROOT/frontend"
PID_FILE="$FRONTEND_DIR/frontend-preview.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "Frontend preview is not running"
  exit 0
fi

PID=$(cat "$PID_FILE")
case "$PID" in
  ''|*[!0-9]*) echo "Invalid frontend PID file" >&2; exit 1 ;;
esac

if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  i=0
  while kill -0 "$PID" 2>/dev/null && [ "$i" -lt 20 ]; do
    sleep 0.1
    i=$((i + 1))
  done
fi
rm -f "$PID_FILE"
echo "Frontend preview stopped"
