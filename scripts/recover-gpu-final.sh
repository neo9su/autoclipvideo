#!/bin/bash
# GPU Service Recovery Script

GPU_SERVER="10.190.0.203"
GPU_USER="neo"

echo "=== GPU Service Recovery ==="

# 1. Check and fix SSH tunnel
TUNNEL_PID=$(lsof -ti :8877)
if [ -n "$TUNNEL_PID" ]; then
    echo "SSH tunnel running (PID: $TUNNEL_PID)"
else
    echo "Starting SSH tunnel..."
    ssh -f -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 8877:127.0.0.1:8877 $GPU_USER@$GPU_SERVER
    sleep 2
fi

# 2. Start GPU service
echo "Starting GPU service..."
ssh $GPU_USER@$GPU_SERVER "cmd /c 'cd /d C:\Users\neo\douyin_processor && C:\Python313\python.exe -m gpu_service.main > C:\Temp\gpu_out.log 2>&1 &' && echo Started"

# 3. Wait and verify
echo "Waiting for service..."
for i in 1 2 3 4 5; do
    sleep 3
    if curl -s --connect-timeout 3 http://localhost:8877/health | grep -q healthy; then
        echo "SUCCESS: GPU service is running!"
        curl -s http://localhost:8877/health
        exit 0
    fi
    echo "[$i/5] Waiting..."
done

echo "WARNING: Service may need manual restart"
exit 1
