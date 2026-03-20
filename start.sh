#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Building frontend..."
cd frontend && npm run build
cd "$SCRIPT_DIR"

echo "==> Starting backend (http://0.0.0.0:8899)..."
cd backend
exec uvicorn main:app --host 0.0.0.0 --port 8899
