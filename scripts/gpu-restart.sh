#!/bin/bash
# Quick GPU Service Restart via Admin Endpoint
# 使用方法: ./gpu-restart.sh [token]

GPU_SERVER="10.190.0.203"
LOCAL_PORT=8877
ADMIN_TOKEN="${1:-}"

echo "=== GPU Service Restart ==="
echo ""

# Step 1: Check current status
echo "Step 1: Checking current status..."
curl -s http://localhost:$LOCAL_PORT/health | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'Health: {d.get(\"health\")}')
    print(f'PID: {d.get(\"pid\")}')
    print(f'Queue: {d.get(\"queue_depth\")} | Busy: {d.get(\"gpu_busy\")}')
except:
    print('Service not responding')
"
echo ""

# Step 2: Try restart via admin endpoint
if [ -n "$ADMIN_TOKEN" ]; then
    echo "Step 2: Restarting via admin endpoint..."
    RESPONSE=$(curl -s -X POST "http://localhost:$LOCAL_PORT/admin/restart?token=$ADMIN_TOKEN" --connect-timeout 5)
    echo "Response: $RESPONSE"
elif [ -n "$GPU_ADMIN_TOKEN" ]; then
    echo "Step 2: Restarting via admin endpoint (env)..."
    RESPONSE=$(curl -s -X POST "http://localhost:$LOCAL_PORT/admin/restart?token=$GPU_ADMIN_TOKEN" --connect-timeout 5)
    echo "Response: $RESPONSE"
else
    echo "Step 2: No admin token available"
    echo "Usage: ./gpu-restart.sh <token>"
    echo "Or set GPU_ADMIN_TOKEN in environment"
    exit 1
fi

# Step 3: Wait for recovery
echo ""
echo "Step 3: Waiting for service recovery..."
for i in 1 2 3 4 5 6; do
    sleep 3
    if curl -s --connect-timeout 2 http://localhost:$LOCAL_PORT/health | grep -q '"healthy"'; then
        echo "✅ Service recovered!"
        curl -s http://localhost:$LOCAL_PORT/health | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'PID: {d.get(\"pid\")}')
print(f'GPU: {d.get(\"cuda\", {}).get(\"device\")}')
print(f'完成: {d.get(\"jobs\")} tasks')
"
        exit 0
    fi
    echo "[$i/6] Waiting..."
done

echo "❌ Failed to recover via admin endpoint"
echo "Trying fallback: SSH restart..."
exit 1
