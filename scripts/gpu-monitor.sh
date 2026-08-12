#!/bin/bash
# GPU Service Monitor - checks health and alerts on issues

TUNNEL_CMD="ssh -f -N -L 8877:localhost:8877 neo@10.190.0.203"
LOG_FILE="/tmp/gpu-monitor.log"

check_gpu() {
    local status
    status=$(curl -s --connect-timeout 5 http://localhost:8877/health 2>/dev/null)
    
    if [ -z "$status" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU service not responding, restarting tunnel..." >> "$LOG_FILE"
        pkill -f "ssh.*203.*8877" 2>/dev/null
        $TUNNEL_CMD 2>/dev/null
        sleep 3
        status=$(curl -s --connect-timeout 5 http://localhost:8877/health 2>/dev/null)
        if [ -n "$status" ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU service recovered after tunnel restart" >> "$LOG_FILE"
        else
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU service STILL DOWN after tunnel restart!" >> "$LOG_FILE"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] REMOTE RECOVERY REQUIRED: SSH to GPU server and restart service" >> "$LOG_FILE"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Command: ssh neo@10.190.0.203 'cd C:\\Users\\neo\\douyin_processor && C:\\Python313\\python.exe -m gpu_service.main'" >> "$LOG_FILE"
        fi
        return 1
    fi
    
    local queue_depth gpu_busy jobs_completed
    queue_depth=$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('queue_depth', -1))" 2>/dev/null)
    gpu_busy=$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('gpu_busy', 'unknown'))" 2>/dev/null)
    jobs_completed=$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('jobs', 0))" 2>/dev/null)
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU: queue=$queue_depth busy=$gpu_busy total_jobs=$jobs_completed" >> "$LOG_FILE"
    
    # Alert if queue is stuck
    if [ "$gpu_busy" = "True" ] && [ "$queue_depth" -gt 100 ] 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALERT: GPU queue stuck! depth=$queue_depth busy=$gpu_busy" >> "$LOG_FILE"
    fi
    
    return 0
}

# Main loop
while true; do
    check_gpu
    sleep 60
done
