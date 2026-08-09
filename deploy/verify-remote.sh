#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://10.190.0.203:8899}"
BASE_URL="${BASE_URL%/}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

check_http() {
  local path="$1"
  local expected="$2"
  local status
  status=$(curl --silent --show-error --output "$TMP_DIR/response" --write-out '%{http_code}' "$BASE_URL$path")
  [[ "$status" == "$expected" ]] || { echo "FAIL $path: HTTP $status (expected $expected)" >&2; exit 1; }
  echo "PASS $path: HTTP $status"
}

check_http "/" 200
check_http "/frontend/" 200
check_http "/api/status" 200
check_http "/docs" 200

curl --silent --show-error "$BASE_URL/health" > "$TMP_DIR/health.json"
python - "$TMP_DIR/health.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload.get('deployment_role') == 'gpu-backend', payload
assert payload.get('media_workers_enabled') is True, payload
required = {'transcription', 'backfill', 'publish', 'enhance', 'creative', 'director', 'qianchuan', 'room-monitors'}
assert required <= set(payload.get('worker_services', [])), payload
print('PASS /health: gpu-backend media workers enabled')
PY

curl --silent --show-error "$BASE_URL/frontend/" > "$TMP_DIR/frontend.html"

# Fetch the referenced production bundle and verify the visible Qianchuan marker.
BUNDLE_PATH=$(python - "$TMP_DIR/frontend.html" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
matches = re.findall(r'<script[^>]+src="([^"]+)"', text)
assert matches, 'frontend index has no script bundle'
print(matches[0])
PY
)
curl --silent --show-error "$BASE_URL/frontend/${BUNDLE_PATH#./}" > "$TMP_DIR/frontend.js"
python - "$TMP_DIR/frontend.js" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
assert '千川投流版' in text or 'qianchuan' in text, 'frontend bundle does not expose Qianchuan UI'
print('PASS /frontend/: Qianchuan UI marker present in production bundle')
PY

curl --silent --show-error "$BASE_URL/api/v2/qianchuan/status" > "$TMP_DIR/qianchuan.json"
python - "$TMP_DIR/qianchuan.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload.get('qianchuan_available') is True, payload
assert payload.get('version'), payload
print(f"PASS /api/v2/qianchuan/status: available (version {payload['version']})")
PY

curl --silent --show-error "$BASE_URL/api/groups" > "$TMP_DIR/groups.json"
python - "$TMP_DIR/groups.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert isinstance(payload, list), type(payload)
if payload:
    required = {'qianchuan_status', 'qianchuan_final_video', 'qianchuan_error'}
    missing = required - payload[0].keys()
    assert not missing, sorted(missing)
print(f"PASS /api/groups: Qianchuan fields present ({len(payload)} groups)")
PY

GPU_STATUS=$(curl --silent --show-error "$BASE_URL/api/gpu/status")
python -c 'import json,sys; payload=json.loads(sys.argv[1]); assert "online" in payload and "watchdog" in payload; print("PASS /api/gpu/status: worker and watchdog fields present")' "$GPU_STATUS"

echo "Remote Qianchuan deployment checks passed for $BASE_URL"
