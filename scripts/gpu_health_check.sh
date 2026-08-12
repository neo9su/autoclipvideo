#!/bin/bash
# GPU服务健康检查脚本

LOG_FILE="/tmp/gpu_health_check.log"
BACKEND_URL="http://localhost:8899/api/gpu/status"
ALERT_THRESHOLD=5  # 连续失败次数

# 检查GPU状态
STATUS=$(curl -s "$BACKEND_URL")
REACHABLE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reachable', False))" 2>/dev/null)
GPU_ONLINE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('gpu_online', False))" 2>/dev/null)

# 检查是否离线
if [ "$REACHABLE" != "True" ] || [ "$GPU_ONLINE" != "True" ]; then
    echo "$(date): ⚠ GPU服务离线 - reachable=$REACHABLE, gpu_online=$GPU_ONLINE" >> "$LOG_FILE"
    
    # 重启SSH隧道
    launchctl stop com.claw.gpu-tunnel 2>/dev/null
    sleep 2
    launchctl start com.claw.gpu-tunnel 2>/dev/null
    
    echo "$(date): 🔧 已尝试重启SSH隧道" >> "$LOG_FILE"
    
    # 等待服务恢复
    sleep 10
    
    # 再次检查
    STATUS2=$(curl -s "$BACKEND_URL")
    REACHABLE2=$(echo "$STATUS2" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reachable', False))" 2>/dev/null)
    GPU_ONLINE2=$(echo "$STATUS2" | python3 -c "import sys,json; print(json.load(sys.stdin).get('gpu_online', False))" 2>/dev/null)
    
    if [ "$REACHABLE2" = "True" ] && [ "$GPU_ONLINE2" = "True" ]; then
        echo "$(date): ✓ GPU服务已恢复" >> "$LOG_FILE"
    else
        echo "$(date): ✗ GPU服务恢复失败，需要人工介入" >> "$LOG_FILE"
    fi
else
    echo "$(date): ✓ GPU服务正常 - reachable=$REACHABLE, gpu_online=$GPU_ONLINE" >> "$LOG_FILE"
fi
