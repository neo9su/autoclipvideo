#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://10.190.0.203:8899}"
BASE_URL="${BASE_URL%/}"

check_http() {
  local path="$1"
  local expected="$2"
  local status
  status=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$BASE_URL$path")
  [[ "$status" == "$expected" ]] || { echo "FAIL $path: HTTP $status (expected $expected)" >&2; exit 1; }
  echo "PASS $path: HTTP $status"
}

check_http "/" 200
check_http "/frontend/" 200
check_http "/api/status" 200
check_http "/docs" 200

GPU_STATUS=$(curl --silent --show-error "$BASE_URL/api/gpu/status")
python -c 'import json,sys; payload=json.loads(sys.argv[1]); assert "online" in payload and "watchdog" in payload; print("PASS /api/gpu/status: worker and watchdog fields present")' "$GPU_STATUS"

echo "Remote deployment checks passed for $BASE_URL"
