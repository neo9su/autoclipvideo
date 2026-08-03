#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

: "${GPU_BACKEND_URL:?Set GPU_BACKEND_URL to the remote GPU backend URL (for example, http://gpu-host:8899)}"
export VITE_API_BASE="${GPU_BACKEND_URL%/}"

printf '%s\n' "==> Building control-plane frontend (remote API: ${GPU_BACKEND_URL%/})..."
cd frontend
npm run build
printf '%s\n' "==> Starting frontend only; no local backend or media worker is started..."
exec npm run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT:-5173}"
