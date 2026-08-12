#!/bin/bash
# 一键恢复 GPU 服务和后端
# 使用方法: ./recover-all.sh

set -e

GPU_SERVER="10.190.0.203"
SSH_USER="neo"
LOCAL_PORT=8877
BACKEND_PORT=8899

echo "========================================"
echo "  GPU Service & Backend Recovery"
echo "========================================"
echo ""

# 检查 GPU 服务
check_gpu() {
    curl -s --connect-timeout 3 http://localhost:$LOCAL_PORT/health 2>/dev/null | grep -q '"healthy"'
}

# 检查后端
check_backend() {
    curl -s --connect-timeout 3 http://localhost:$BACKEND_PORT/api/status 2>/dev/null | grep -q -E '"status"|"enabled_rooms"'
}

# 步骤 1: 检查当前状态
echo "Step 1: Checking current status..."
if check_gpu && check_backend; then
    echo "✅ All services are healthy"
    exit 0
fi
echo "❌ Some services need recovery"
echo ""

# 步骤 2: 清理并重建 SSH 隧道
echo "Step 2: Fixing SSH tunnel..."
lsof -ti :$LOCAL_PORT | xargs kill -9 2>/dev/null || true
sleep 1
ssh -f -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L ${LOCAL_PORT}:127.0.0.1:${LOCAL_PORT} ${SSH_USER}@${GPU_SERVER}
sleep 2
echo "✅ SSH tunnel established"
echo ""

# 步骤 3: 启动 GPU 服务
if ! check_gpu; then
    echo "Step 3: Starting GPU service..."
    ssh -o ConnectTimeout=10 ${SSH_USER}@${GPU_SERVER} "cmd /c 'cd /d C:\\Users\\neo\\douyin_processor && C:\\Python313\\python.exe -m gpu_service.main > C:\\Temp\\gpu_out.log 2>&1 &'"
    echo "GPU service start command sent"
    
    # 等待服务启动
    echo "Waiting for GPU service to start..."
    for i in 1 2 3 4 5 6; do
        sleep 3
        if check_gpu; then
            echo "✅ GPU service is healthy"
            break
        fi
        echo "[$i/6] Waiting..."
    done
else
    echo "✅ GPU service already running"
fi
echo ""

# 步骤 4: 重启后端（如果 GPU 之前离线）
if check_gpu && ! curl -s http://localhost:$BACKEND_PORT/api/gpu/status | grep -q '"online":true'; then
    echo "Step 4: Restarting backend to reconnect GPU..."
    launchctl stop com.claw.douyin-backend 2>/dev/null || true
    sleep 3
    launchctl start com.claw.douyin-backend 2>/dev/null || true
    echo "Backend restarting..."
    
    # 等待后端启动
    for i in 1 2 3 4 5; do
        sleep 5
        if check_backend; then
            echo "✅ Backend is healthy"
            break
        fi
        echo "[$i/5] Waiting for backend..."
    done
else
    echo "✅ Backend already connected to GPU"
fi
echo ""

# 最终验证
echo "========================================"
echo "  Final Status"
echo "========================================"
echo ""
echo "GPU Service:"
curl -s http://localhost:$LOCAL_PORT/health | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  Health: {d.get(\"health\")} | GPU: {d.get(\"cuda\", {}).get(\"device\")}')
print(f'  Jobs: {d.get(\"jobs\")} | Queue: {d.get(\"queue_depth\")}')
"

echo ""
echo "Backend:"
curl -s http://localhost:$BACKEND_PORT/api/gpu/status | python3 -c "
import sys, json
d = json.load(sys.stdin)
status = 'Online' if d.get('online') else 'Offline'
print(f'  GPU: {status} | Busy: {d.get(\"busy\", False)}')
"

echo ""
echo "✅ Recovery complete!"
