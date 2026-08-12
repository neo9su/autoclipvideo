#!/bin/bash
# GPU服务健康检查脚本

BACKEND_URL="http://localhost:8899/api/gpu/status"
LOG_FILE="/tmp/gpu_health_check.log"

# 检查GPU状态
STATUS=$(curl -s "$BACKEND_URL")
REACHABLE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reachable', False))" 2>/dev/null)
GPU_ONLINE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('gpu_online', False))" 2>/dev/null)
QUEUE_DEPTH=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('health', {}).get('queue_depth', 0))" 2>/dev/null)

# 记录状态
if [ "$REACHABLE" = "True" ] && [ "$GPU_ONLINE" = "True" ]; then
    echo "$(date): ✓ GPU在线 | reachable=$REACHABLE gpu_online=$GPU_ONLINE queue=$QUEUE_DEPTH" >> "$LOG_FILE"
else
    echo "$(date): ✗ GPU离线 | reachable=$REACHABLE gpu_online=$GPU_ONLINE queue=$QUEUE_DEPTH" >> "$LOG_FILE"
    # 尝试重启SSH隧道
    launchctl stop com.claw.gpu-tunnel 2>/dev/null
    sleep 2
    launchctl start com.claw.gpu-tunnel 2>/dev/null
    echo "$(date): 🔧 已尝试重启SSH隧道" >> "$LOG_FILE"
fi
