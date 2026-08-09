#!/bin/sh
set -eu

# launchd owns restart policy. Keep this process in the foreground.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
FRONTEND_DIR="$REPO_ROOT/frontend"

if [ ! -f "$FRONTEND_DIR/dist/index.html" ]; then
  echo "frontend/dist/index.html is missing; build the frontend before loading launchd" >&2
  exit 1
fi

cd "$FRONTEND_DIR"
exec npm run preview -- --host 127.0.0.1 --port 5173
