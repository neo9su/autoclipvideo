#!/bin/bash
# GPU服务SSH隧道自动重连脚本

TUNNEL_CMD="ssh neo@10.190.0.203 python C:\\Users\\neo\\douyin_processor\\gpu_service\\main.py 2>&1 &"
LOG_FILE="/tmp/gpu_tunnel_reconnect.log"
PID_FILE="/tmp/gpu_tunnel.pid"

# 检查是否已有SSH隧道在运行
if pgrep -f "ssh neo@10.190.0.203 python" > /dev/null; then
    echo "$(date): SSH隧道已在运行，跳过" >> "$LOG_FILE"
    exit 0
fi

echo "$(date): 启动SSH隧道..." >> "$LOG_FILE"
eval $TUNNEL_CMD &
echo $! > "$PID_FILE"
echo "$(date): SSH隧道已启动，PID: $(cat $PID_FILE)" >> "$LOG_FILE"
