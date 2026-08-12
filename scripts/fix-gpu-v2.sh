#!/bin/bash
# GPU Service Recovery Script v2

GPU_SERVER="10.190.0.203"
GPU_USER="neo"
GPU_DIR="C:\Users\neo\douyin_processor"
PYTHON="C:\Python313\python.exe"
PORT=8877
TUNNEL_PORT=8877

echo "=== GPU Service Recovery ==="
echo ""

# Step 1: Check SSH connectivity
echo "Step 1: Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no ${GPU_USER}@${GPU_SERVER} 'echo OK' > /dev/null 2>&1; then
    echo "ERROR: SSH connection failed"
    exit 1
fi
echo "OK"

# Step 2: Kill existing GPU processes
echo "Step 2: Stopping existing GPU processes..."
ssh -o ConnectTimeout=10 ${GPU_USER}@${GPU_SERVER} 'taskkill /F /IM python.exe /FI "WINDOWTITLE eq *gpu*" 2>nul || taskkill /F /IM python.exe /FI "IMAGENAME eq python.exe"' 2>/dev/null
sleep 3

# Step 3: Clear tunnel port
echo "Step 3: Clearing local port ${TUNNEL_PORT}..."
lsof -ti :${TUNNEL_PORT} | xargs kill -9 2>/dev/null || true
sleep 1

# Step 4: Start tunnel
echo "Step 4: Establishing SSH tunnel..."
ssh -f -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=10 -L ${TUNNEL_PORT}:127.0.0.1:${PORT} ${GPU_USER}@${GPU_SERVER}
sleep 2

# Step 5: Start GPU service
echo "Step 5: Starting GPU service..."
ssh -o ConnectTimeout=10 ${GPU_USER}@${GPU_SERVER} "cd ${GPU_DIR} && start /B ${PYTHON} -m gpu_service.main"
echo "Start command sent"

# Step 6: Wait for service
echo "Step 6: Waiting for service to start..."
for i in 1 2 3 4 5 6 7 8; do
    sleep 3
    if curl -s --connect-timeout 3 http://localhost:${TUNNEL_PORT}/health 2>/dev/null | grep -q '"healthy"'; then
        echo "SUCCESS: GPU service is healthy!"
        curl -s http://localhost:${TUNNEL_PORT}/health
        exit 0
    fi
    echo "[$i/8] Waiting..."
done

echo "ERROR: Service failed to start within 24 seconds"
exit 1
