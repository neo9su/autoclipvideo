#!/bin/bash
# Deploy OmniVoice TTS service on GPU server
# Usage: GPU_BACKEND_HOST=10.190.0.203 GPU_BACKEND_DIR=~/douyin_processor ./deploy_omnivoice_service.sh

set -euo pipefail

REMOTE="${GPU_BACKEND_HOST:?Set GPU_BACKEND_HOST}"
DIR="${GPU_BACKEND_DIR:?Set GPU_BACKEND_DIR}"

echo "Deploying OmniVoice service to ${REMOTE}:${DIR}..."

# Sync the OmniVoice service script
rsync -az \
  --exclude='.git' \
  --exclude='__pycache__' \
  gpu_service_src/omnivoice_service.py \
  "${REMOTE}:${DIR}/omnivoice_service.py"

# Create startup script
ssh "${REMOTE}" "cat > ${DIR}/start_omnivoice.bat << 'BAT'
@echo off
setlocal
cd /d %~dp0
echo Starting OmniVoice TTS service on port 8879...
python omnivoice_service.py --port 8879
pause
BAT
"

# Create install script
ssh "${REMOTE}" "cat > ${DIR}/install_omnivoice.bat << 'BAT'
@echo off
setlocal
cd /d %~dp0
echo Installing OmniVoice...
pip install omnivoice soundfile --quiet
echo Installation complete!
pause
BAT
"

echo "Deployment complete!"
echo "To install: rdp to ${REMOTE} and run install_omnivoice.bat"
echo "To start: rdp to ${REMOTE} and run start_omnivoice.bat"
