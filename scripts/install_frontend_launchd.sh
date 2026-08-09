#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
LABEL=${FRONTEND_LAUNCHD_LABEL:-com.douyin-recorder.frontend}
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"

command -v npm >/dev/null 2>&1 || { echo "npm is required" >&2; exit 1; }
[ -f "$REPO_ROOT/frontend/dist/index.html" ] || {
  echo "frontend/dist/index.html is missing; run (cd frontend && npm run build) first" >&2
  exit 1
}

mkdir -p "$PLIST_DIR"
python3 - "$PLIST_PATH" "$LABEL" "$REPO_ROOT/scripts/run_frontend_preview.sh" "$REPO_ROOT/frontend/frontend-preview.log" <<'PY'
import plistlib
import sys
from pathlib import Path

path, label, program, log_path = sys.argv[1:]
data = {
    "Label": label,
    "ProgramArguments": [program],
    "WorkingDirectory": str(Path(program).parent.parent),
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ProcessType": "Interactive",
    "StandardOutPath": log_path,
    "StandardErrorPath": log_path,
}
with open(path, "wb") as stream:
    plistlib.dump(data, stream, sort_keys=False)
PY

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "Loaded $LABEL"
echo "Service: launchctl print gui/$(id -u)/$LABEL"
echo "URL: http://127.0.0.1:5173"
