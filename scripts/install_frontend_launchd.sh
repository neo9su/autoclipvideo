#!/usr/bin/env bash
set -euo pipefail

# Install the UI-only Vite preview as a user launchd service. Re-running this
# script replaces the same label and never starts a second preview listener.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
LABEL="com.douyin-recorder.frontend-preview"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$REPO_ROOT/frontend/.launchd"

command -v launchctl >/dev/null || { echo "launchctl is required on macOS" >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required" >&2; exit 1; }
[[ -d "$FRONTEND_DIR" ]] || { echo "frontend directory not found" >&2; exit 1; }

mkdir -p "$PLIST_DIR" "$LOG_DIR"
cd "$FRONTEND_DIR"
npm ci
npm run build

USER_ID="$(id -u)"
DOMAIN="gui/$USER_ID"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v npm)</string>
    <string>run</string>
    <string>preview</string>
    <string>--</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>5173</string>
  </array>
  <key>WorkingDirectory</key><string>$FRONTEND_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/stdout.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/stderr.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST_PATH"
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl kickstart -k "$DOMAIN/$LABEL"

for _ in {1..20}; do
  if curl --silent --fail --max-time 1 http://127.0.0.1:5173/ >/dev/null; then
    echo "frontend preview ready: http://127.0.0.1:5173"
    exit 0
  fi
  sleep 1
done
echo "frontend preview did not become ready; inspect launchd logs" >&2
exit 1
