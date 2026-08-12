#!/bin/bash
# GPU 服务一键修复脚本
# 用法: ./fix-gpu-service.sh

set -e

GPU_HOST="10.190.0.203"
GPU_USER="neo"
GPU_PORT=8877

echo "=== GPU Service Fix Script ==="
echo "Target: ${GPU_USER}@${GPU_HOST}:${GPU_PORT}"
echo ""

# 检查连通性
echo "Step 1: Checking connectivity..."
if ! ping -c 2 ${GPU_HOST} > /dev/null; then
    echo "ERROR: Cannot reach GPU server"
    exit 1
fi
echo "  ✓ GPU server is reachable"
echo ""

# 检查 SSH 连接
echo "Step 2: Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 ${GPU_USER}@${GPU_HOST} "echo OK" 2>/dev/null | grep -q "OK"; then
    echo "ERROR: SSH connection failed"
    exit 1
fi
echo "  ✓ SSH connection successful"
echo ""

# 修复 GPU 服务
echo "Step 3: Fixing GPU service..."
ssh ${GPU_USER}@${GPU_HOST} "
    echo 'Stopping GPU service...'
    taskkill /F /IM python.exe 2>nul
    timeout /t 3 /nobreak
    
    echo 'Cleaning log files...'
    cd C:\\Users\\neo\\douyin_processor\\gpu_service
    del /F /Q gpu_service.log 2>nul
    del /F /Q gpu_service_old.log 2>nul
    
    echo 'Creating log directory...'
    mkdir C:\\Temp\\gpu_logs 2>nul
    cd C:\\Temp\\gpu_logs
    
    echo 'Starting GPU service...'
    set GPU_LOG_DIR=C:\\Temp\\gpu_logs
    start /b C:\\Python313\\python.exe C:\\Users\\neo\\douyin_processor\\gpu_service\\main.py
    
    echo 'Waiting for service to start...'
    timeout /t 10 /nobreak
    
    echo 'Verification:'
    tasklist /FI \"IMAGENAME eq python.exe\" /V
    netstat -ano | findstr :${GPU_PORT}
" 2>&1 || echo "Remote command failed (may need manual intervention)"
echo ""

# 验证服务
echo "Step 4: Verifying service..."
sleep 5
if curl -s --max-time 10 http://${GPU_HOST}:${GPU_PORT}/health 2>/dev/null | grep -q "online"; then
    echo "  ✓ GPU service is running (direct)"
elif curl -s --max-time 5 http://localhost:${GPU_PORT}/health 2>/dev/null | grep -q "online"; then
    echo "  ✓ GPU service is running (via tunnel)"
else
    echo "  ⚠ Service not reachable, may need manual intervention"
fi
echo ""

echo "=== Fix Complete ==="
echo "Check service status:"
echo "  Direct: curl http://${GPU_HOST}:${GPU_PORT}/health"
echo "  Tunnel: curl http://localhost:${GPU_PORT}/health"
