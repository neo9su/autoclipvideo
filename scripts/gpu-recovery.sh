#!/bin/bash
# GPU Service Recovery Script
# 使用方法: ./gpu-recovery.sh

GPU_SERVER="10.190.0.203"
LOCAL_PORT=8877
SSH_USER="neo"

echo "=== GPU Service Recovery ==="
echo ""

# Step 1: Check if service is healthy
check_health() {
    curl -s --connect-timeout 3 http://localhost:$LOCAL_PORT/health 2>/dev/null | grep -q '"healthy"'
}

if check_health; then
    echo "✅ GPU service is already healthy"
    curl -s http://localhost:$LOCAL_PORT/health | python3 -m json.tool 2>/dev/null
    exit 0
fi

echo "❌ GPU service is not healthy"
echo ""

# Step 2: Check SSH tunnel
TUNNEL_PID=$(lsof -ti :$LOCAL_PORT)
if [ -z "$TUNNEL_PID" ]; then
    echo "Step 1: Establishing SSH tunnel..."
    ssh -f -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L ${LOCAL_PORT}:127.0.0.1:${LOCAL_PORT} ${SSH_USER}@${GPU_SERVER}
    sleep 2
    if ! check_health; then
        echo "WARNING: SSH tunnel established but service still not responding"
    fi
else
    echo "Step 1: SSH tunnel already running (PID: $TUNNEL_PID)"
fi

# Step 3: Try to restart via HTTP (if supported)
echo "Step 2: Attempting HTTP restart..."
HTTP_RESPONSE=$(curl -s -X POST http://localhost:$LOCAL_PORT/admin/restart --connect-timeout 5 2>/dev/null)
if [ -n "$HTTP_RESPONSE" ]; then
    echo "HTTP restart response: $HTTP_RESPONSE"
    sleep 5
    if check_health; then
        echo "✅ Service recovered via HTTP"
        exit 0
    fi
fi

# Step 4: Use SSH as fallback
echo "Step 3: Using SSH to restart service..."
ssh -o ConnectTimeout=10 ${SSH_USER}@${GPU_SERVER} "cmd /c 'taskkill /F /IM python.exe /FI \"WINDOWTITLE eq *gpu*\" 2>nul && cd /d C:\\Users\\neo\\douyin_processor && start /min C:\\Python313\\python.exe -m gpu_service.main'" 2>/dev/null

# Step 5: Wait for recovery
echo "Step 4: Waiting for service recovery..."
for i in 1 2 3 4 5 6 7 8; do
    sleep 3
    if check_health; then
        echo "✅ GPU service recovered!"
        curl -s http://localhost:$LOCAL_PORT/health | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'PID: {d.get(\"pid\")}')
print(f'GPU: {d.get(\"cuda\", {}).get(\"device\")}')
print(f'完成: {d.get(\"jobs\")} tasks')
"
        exit 0
    fi
    echo "[$i/8] Waiting..."
done

echo "❌ Failed to recover GPU service"
echo "Please try manual recovery:"
echo "  1. RDP to 10.190.0.203"
echo "  2. Run: cd C:\\Users\\neo\\douyin_processor"
echo "  3. Run: C:\\Python313\\python.exe -m gpu_service.main"
exit 1
