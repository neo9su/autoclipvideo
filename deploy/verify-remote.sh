#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://10.190.0.203:8899}"
BASE_URL="${BASE_URL%/}"
MEDIA_BASENAME="${2:-}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

check_http() {
  local path="$1"
  local expected="$2"
  local status
  status=$(curl --silent --show-error --location --output "$TMP_DIR/response" --write-out '%{http_code}' "$BASE_URL$path")
  [[ "$status" == "$expected" ]] || { echo "FAIL $path: HTTP $status (expected $expected)" >&2; exit 1; }
  echo "PASS $path: HTTP $status"
}

check_http "/" 200
check_http "/frontend/" 200
check_http "/api/status" 200
check_http "/docs" 200

curl --silent --show-error --location "$BASE_URL/health" > "$TMP_DIR/health.json"
python - "$TMP_DIR/health.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload.get('deployment_role') == 'gpu-backend', payload
assert payload.get('media_workers_enabled') is True, payload
required = {'transcription', 'backfill', 'publish', 'enhance', 'creative', 'director', 'qianchuan', 'room-monitors'}
assert required <= set(payload.get('worker_services', [])), payload
assert payload.get('qianchuan_api_loaded') is True, payload
policy = payload.get('recording_policy', {})
assert policy.get('min_duration_seconds') == 28.0, policy
assert policy.get('max_segment_duration_seconds') == 2700.0, policy
print('PASS /health: gpu-backend media workers enabled')
print('PASS /health: recording policy is 28s minimum / 2700s maximum segment')
print('PASS /health: Qianchuan API router loaded')
policy = payload.get('recording_policy')
assert policy == {
    'min_duration_seconds': 28.0,
    'max_segment_duration_seconds': 2700,
}, policy
print('PASS /health: recording policy is 28s minimum / 2700s segment maximum')
PY

curl --silent --show-error --location "$BASE_URL/openapi.json" > "$TMP_DIR/openapi.json"
python - "$TMP_DIR/openapi.json" <<'PY'
import json, sys
paths = set(json.load(open(sys.argv[1])).get('paths', {}))
required = {
    '/api/v2/qianchuan/status',
    '/api/v2/qianchuan/generate',
    '/api/v2/qianchuan/compose',
    '/api/v2/qianchuan/group/{group_id}/result',
}
missing = sorted(required - paths)
assert not missing, f'missing Qianchuan OpenAPI routes: {missing}'
print('PASS /openapi.json: Qianchuan status/generate/compose/result routes exposed')
PY

curl --silent --show-error --location "$BASE_URL/frontend/" > "$TMP_DIR/frontend.html"

# Fetch the referenced production bundle and verify the visible Qianchuan marker.
BUNDLE_PATH=$(python - "$TMP_DIR/frontend.html" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
matches = re.findall(r'<script[^>]+src="([^"]+)"', text)
assert matches, 'frontend index has no script bundle'
print(matches[0])
PY
)
curl --silent --show-error --location "$BASE_URL/frontend/${BUNDLE_PATH#./}" > "$TMP_DIR/frontend.js"
python - "$TMP_DIR/frontend.js" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
assert '千川投流版' in text or 'qianchuan' in text, 'frontend bundle does not expose Qianchuan UI'
print('PASS /frontend/: Qianchuan UI marker present in production bundle')
PY

curl --silent --show-error --location "$BASE_URL/api/v2/qianchuan/status" > "$TMP_DIR/qianchuan.json"
python - "$TMP_DIR/qianchuan.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload.get('qianchuan_available') is True, payload
assert payload.get('version'), payload
assert any(route['method'] == 'POST' and route['path'].endswith('/generate') for route in payload['routes']), payload
assert payload['media_contract']['path_namespace'] == 'container-only', payload
print(f"PASS /api/v2/qianchuan/status: available (version {payload['version']})")
print('PASS qianchuan route contract and container-only media contract')
PY

curl --silent --show-error --location "$BASE_URL/api/v2/director/status" > "$TMP_DIR/director.json"
python - "$TMP_DIR/director.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload.get('director_mode_available') is True, payload
assert payload.get('version'), payload
assert any(route['method'] == 'POST' and route['path'].endswith('/generate-script') for route in payload['routes']), payload
print(f"PASS /api/v2/director/status: available (version {payload['version']})")
PY

curl --silent --show-error --location "$BASE_URL/api/groups" > "$TMP_DIR/groups.json"
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

GPU_STATUS=$(curl --silent --show-error --location "$BASE_URL/api/gpu/status")
python -c 'import json,sys; payload=json.loads(sys.argv[1]); assert "online" in payload and "watchdog" in payload; print("PASS /api/gpu/status: worker and watchdog fields present")' "$GPU_STATUS"

# Exercise a real POST route contract. A deliberately invalid boundary value
# must be rejected by FastAPI validation; a status-only stub cannot satisfy it.
POST_STATUS=$(curl --silent --show-error --location --output "$TMP_DIR/post-response" --write-out '%{http_code}' \
  -X POST "$BASE_URL/api/v2/qianchuan/generate" \
  -H 'content-type: application/json' --data '{"group_id":0}')
case "$POST_STATUS" in
  400|422) echo "PASS /api/v2/qianchuan/generate: validation response HTTP $POST_STATUS" ;;
  *) echo "FAIL /api/v2/qianchuan/generate: expected HTTP 400 or 422, got $POST_STATUS" >&2; exit 1 ;;
esac

if [[ -n "$MEDIA_BASENAME" ]]; then
  curl --silent --show-error --location --get \
    --data-urlencode "filename=$MEDIA_BASENAME" \
    "$BASE_URL/api/v2/qianchuan/media/audit" > "$TMP_DIR/media-audit.json"
  python - "$TMP_DIR/media-audit.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload.get('evidence', {}).get('filename'), payload
assert payload.get('evidence', {}).get('mp4', {}).get('size_bytes', 0) > 0, payload
assert payload.get('evidence', {}).get('srt', {}).get('size_bytes', 0) > 0, payload
assert payload.get('ok') is True, payload
print('PASS /api/v2/qianchuan/media/audit: MP4 and non-empty SRT are readable')
PY
fi

echo "Remote Qianchuan deployment checks passed for $BASE_URL"
