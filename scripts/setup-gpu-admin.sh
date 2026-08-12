#!/bin/bash
# Setup GPU Service Admin Endpoints
# This script deploys the admin endpoints and configures authentication

GPU_SERVER="10.190.0.203"
SSH_USER="neo"
REMOTE_DIR="C:\\Users\\neo\\douyin_processor"

# Generate a secure random token
ADMIN_TOKEN=$(openssl rand -hex 32)
echo "Generated ADMIN_RESTART_TOKEN: $ADMIN_TOKEN"
echo ""
echo "========================================"
echo "  GPU Service Admin Setup"
echo "========================================"
echo ""

# Step 1: Deploy updated main.py
echo "Step 1: Deploying updated main.py..."
scp /Users/claw/work/douyin-recorder/gpu_service/main.py "${SSH_USER}@${GPU_SERVER}:${REMOTE_DIR}/main.py"
echo "✅ main.py deployed"
echo ""

# Step 2: Create env file with token
echo "Step 2: Creating .env file..."
ssh "${SSH_USER}@${GPU_SERVER}" "echo 'GPU_API_TOKEN='${ADMIN_TOKEN} > ${REMOTE_DIR}/.env && echo 'ADMIN_RESTART_TOKEN='${ADMIN_TOKEN} >> ${REMOTE_DIR}/.env && echo 'PORT=8877' >> ${REMOTE_DIR}/.env"
echo "✅ .env file created"
echo ""

# Step 3: Restart GPU service via HTTP (once deployed)
echo "Step 3: Instructions for restart:"
echo "    curl -X POST 'http://${GPU_SERVER}:8877/admin/restart?token=${ADMIN_TOKEN}'"
echo ""

echo "========================================"
echo "  Setup Complete"
echo "========================================"
echo ""
echo "Admin Endpoints:"
echo "  POST http://${GPU_SERVER}:8877/admin/restart"
echo "  GET  http://${GPU_SERVER}:8877/admin/health"
echo ""
echo "Usage Example:"
echo "  curl -X POST 'http://${GPU_SERVER}:8877/admin/restart?token=${ADMIN_TOKEN}'"
echo ""
echo "Save this token for future restarts:"
echo "  export ADMIN_TOKEN='${ADMIN_TOKEN}'"
echo "  curl -X POST \"http://${GPU_SERVER}:8877/admin/restart?token=\$ADMIN_TOKEN\""
