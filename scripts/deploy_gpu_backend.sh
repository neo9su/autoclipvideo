#!/usr/bin/env bash
set -euo pipefail

: "${GPU_BACKEND_HOST:?Set the SSH host for the GPU server}"
: "${GPU_BACKEND_DIR:?Set the deployment directory on the GPU server}"
: "${GPU_BACKEND_ENV_FILE:?Set the local path to the filled remote deployment env file}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REMOTE="${GPU_BACKEND_HOST}"

rsync -az --delete \
  --exclude '.git' --exclude 'recordings/' --exclude 'data/' --exclude 'voice_output/' \
  "$REPO_ROOT/" "$REMOTE:$GPU_BACKEND_DIR/"
scp "$GPU_BACKEND_ENV_FILE" "$REMOTE:$GPU_BACKEND_DIR/deploy/gpu-backend.env"
ssh "$REMOTE" "cd '$GPU_BACKEND_DIR' && docker compose --env-file deploy/gpu-backend.env -f deploy/docker-compose.gpu-backend.yml up -d --build && docker compose --env-file deploy/gpu-backend.env -f deploy/docker-compose.gpu-backend.yml ps"
