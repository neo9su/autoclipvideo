#!/bin/bash
# Deploy GPU Service Admin Endpoints
# 使用方法: ./deploy-gpu-admin.sh

set -e

GPU_SERVER="10.190.0.203"
SSH_USER="neo"
REMOTE_DIR="C:\\Users\\neo\\douyin_processor"
LOCAL_GPU_DIR="/Users/claw/work/douyin-recorder/gpu_service"

echo "========================================"
echo "  Deploy GPU Admin Endpoints"
echo "========================================"
echo ""

# Step 1: Generate token
ADMIN_TOKEN=$(openssl rand -hex 32)
echo "Step 1: Generating token..."
echo "  Token: $ADMIN_TOKEN"
echo ""

# Step 2: Create .env file locally
ENV_FILE="$LOCAL_GPU_DIR/.env"
cat > "$ENV_FILE" << ENVEOF
GPU_API_TOKEN=$ADMIN_TOKEN
ADMIN_RESTART_TOKEN=$ADMIN_TOKEN
PORT=8877
STORAGE_DIR=C:\\Users\\neo\\douyin_recordings
ENVEOF
echo "Step 2: Created local .env file"
echo ""

# Step 3: Deploy main.py
echo "Step 3: Deploying main.py..."
scp "$LOCAL_GPU_DIR/main.py" "${SSH_USER}@${GPU_SERVER}:/"
ssh "${SSH_USER}@${GPU_SERVER}" "cp /main.py ${REMOTE_DIR}/main.py && rm /main.py"
echo "  ✅ main.py deployed"
echo ""

# Step 4: Deploy .env
echo "Step 4: Deploying .env..."
scp "$ENV_FILE" "${SSH_USER}@${GPU_SERVER}:/"
ssh "${SSH_USER}@${GPU_SERVER}" "cp /.env ${REMOTE_DIR}/.env && rm /.env"
echo "  ✅ .env deployed"
echo ""

# Step 5: Create health check script
echo "Step 5: Creating health check script..."
ssh "${SSH_USER}@${GPU_SERVER}" "cat > ${REMOTE_DIR}/check-gpu.py << 'PYEOF'
import requests, sys, time, os, subprocess

try:
    r = requests.get('http://localhost:8877/health', timeout=5)
    if r.status_code == 200 and r.json().get('health') == 'healthy':
        print('GPU service is healthy')
        sys.exit(0)
except Exception as e:
    print(f'GPU service unhealthy: {e}')

print('Restarting GPU service...')
os.system('taskkill /F /IM python.exe /FI \"IMAGENAME eq python.exe\" 2>nul')
time.sleep(3)
subprocess.Popen([
    r'C:\\Python313\\python.exe', '-m', 'gpu_service.main'
], cwd=r'C:\\Users\\neo\\douyin_processor',
stdout=open(r'C:\\Temp\\gpu.out.log', 'w'),
stderr=open(r'C:\\Temp\\gpu.err.log', 'w'))
print('Restart command sent')
PYEOF"
echo "  ✅ check-gpu.py created"
echo ""

# Step 6: Create batch file for scheduled task
echo "Step 6: Creating batch file..."
ssh "${SSH_USER}@${GPU_SERVER}" "cat > ${REMOTE_DIR}/check-gpu.bat << 'BATEOF'
@echo off
title GPU Health Check
cd /d C:\\Users\\neo\\douyin_processor
python check-gpu.py
if %ERRORLEVEL% NEQ 0 (
    echo %DATE% %TIME% - Restart attempted >> restart.log
)
BATEOF"
echo "  ✅ check-gpu.bat created"
echo ""

# Step 7: Set up scheduled task
echo "Step 7: Setting up scheduled task..."
ssh "${SSH_USER}@${GPU_SERVER}" "schtasks /create /tn \"GPUHealthMonitor\" /tr \"cmd /c ${REMOTE_DIR}\\check-gpu.bat\" /sc minute /mo 5 /rl highest /f 2>nul || echo Scheduled task already exists"
echo "  ✅ Scheduled task configured (every 5 minutes)"
echo ""

# Step 8: Instructions for manual restart
echo "========================================"
echo "  Deployment Complete"
echo "========================================"
echo ""
echo "Admin Token: $ADMIN_TOKEN"
echo ""
echo "Restart commands:"
echo "  # From remote GPU server:"
echo "  curl -X POST 'http://localhost:8877/admin/restart?token=$ADMIN_TOKEN'"
echo ""
echo "  # From Mac (via SSH tunnel):"
echo "  curl -X POST 'http://localhost:8877/admin/restart?token=$ADMIN_TOKEN'"
echo ""
echo "  # With Authorization header:"
echo "  curl -X POST http://localhost:8877/admin/restart -H 'Authorization: Bearer $ADMIN_TOKEN'"
echo ""
echo "Health check:"
echo "  curl http://localhost:8877/admin/health"
echo ""
echo "Save this token for future use:"
echo "  export GPU_ADMIN_TOKEN='$ADMIN_TOKEN'"
