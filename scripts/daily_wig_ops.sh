#!/usr/bin/env bash
set -u

mode="${1:-daily}"
report_dir="${WIG_OPS_REPORT_DIR:-reports/wig-ops}"
mkdir -p "$report_dir"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
report="$report_dir/${mode}-${timestamp}.md"
{
  echo "# 小维 ${mode} 巡检"
  echo
  echo "- 时间（UTC）：$timestamp"
  echo "- 控制面：$(uname -s)"
  echo "- GPU 执行节点：remote-gpu（本脚本不启动本地媒体作业）"
  echo
  echo "## 控制面资源"
  df -h . 2>/dev/null || true
  echo
  echo "## 远端服务（可选配置 REMOTE_BACKEND_URL）"
  if [ -n "${REMOTE_BACKEND_URL:-}" ]; then
    curl --silent --show-error --max-time 10 "$REMOTE_BACKEND_URL/api/status" || echo "API unavailable"
    echo
    curl --silent --show-error --max-time 10 "$REMOTE_BACKEND_URL/api/gpu/status" || echo "GPU status unavailable"
  else
    echo "未配置远端地址；请由部署环境注入 REMOTE_BACKEND_URL 后执行网络检查。"
  fi
  echo
  echo "## 告警阈值"
  echo "- 磁盘剩余空间 <20%"
  echo "- 网络延迟 >100ms 或丢包 >1%"
  echo "- GPU 温度、显存、驱动、CUDA、FFmpeg：在 Windows GPU 节点执行"
  echo
  if [ "$mode" = "weekly" ]; then
    echo "## 周报"
    echo "请汇总本周 API 可用性、队列延迟、GPU 作业耗时/资源消耗，并据此调整并行数与分辨率。"
  fi
} | tee "$report"
echo "Report written to $report"
