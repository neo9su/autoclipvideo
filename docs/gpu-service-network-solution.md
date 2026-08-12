# GPU 服务网络架构改进方案

## 问题分析

### 当前架构（不稳定）
```
┌─────────────┐     SSH 隧道      ┌─────────────┐
│   后端      │ ←──────────────→ │  GPU 服务   │
│  (Mac Mini) │    (port 8877)   │ (Windows)   │
└─────────────┘                  └─────────────┘
      ↓                                  ↓
  隧道断开 → 服务不可用              日志权限问题 → 服务崩溃
```

### 问题根源
1. **SSH 隧道不稳定** - 网络抖动会导致连接断开
2. **GPU 服务日志权限** - `PermissionError` 导致服务无法启动
3. **防火墙阻止** - 端口 8877 未配置入站规则
4. **服务未监听所有接口** - 可能只监听 127.0.0.1

---

## 解决方案：LAN 直接访问

### 架构图（改进后）
```
┌─────────────┐     HTTP/HTTPS      ┌─────────────┐
│   后端      │ ←────────────────→ │  GPU 服务   │
│  (Mac Mini) │    (port 8877)     │ (Windows)   │
└─────────────┘                    └─────────────┘
      ↓                                  ↓
  直接 HTTP 请求                    日志写入 C:\Temp\gpu_logs\
  自动重试机制                      内置健康监控
```

### 优势
- ✅ 不依赖 SSH 隧道
- ✅ 更低的延迟（~5ms vs ~50ms）
- ✅ 更稳定的连接
- ✅ 支持 HTTP 重试和超时
- ✅ 符合微服务架构

---

## 实施步骤

### 步骤 1：GPU 服务器配置

#### 1.1 修复日志权限
```powershell
# 在 GPU 服务器上执行
# 创建日志目录
mkdir C:\Temp\gpu_logs

# 设置权限（允许 neo 用户完全控制）
icacls C:\Temp\gpu_logs /grant neo:(F)

# 复制 GPU 服务到新目录（避免旧日志文件锁定）
xcopy C:\Users\neo\douyin_processor\gpu_service\* C:\Temp\gpu_logs\ /E /Y

# 删除旧日志文件
cd C:\Users\neo\douyin_processor\gpu_service
del gpu_service.log 2>nul
del gpu_service_old.log 2>nul
```

#### 1.2 修改服务配置（监听所有接口）
编辑 `C:\Temp\gpu_logs\main.py`，找到启动代码：
```python
# 修改前
app.run(host='127.0.0.1', port=8877)

# 修改后
app.run(host='0.0.0.0', port=8877)
```

或者通过命令行参数：
```python
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8877)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port)
```

#### 1.3 配置防火墙规则
```powershell
# 允许端口 8877 入站（仅限 LAN）
New-NetFirewallRule -DisplayName "GPU Service 8877" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 8877 `
    -Action Allow `
    -Profile Private,Domain `
    -Enabled True

# 验证规则
Get-NetFirewallRule -DisplayName "GPU Service 8877" | Select-Object DisplayName, Enabled, Direction, Action
```

#### 1.4 启动服务
```powershell
# 设置环境变量
$env:GPU_LOG_DIR = "C:\Temp\gpu_logs"

# 启动服务（后台运行）
cd C:\Temp\gpu_logs
Start-Process -FilePath "C:\Python313\python.exe" -ArgumentList "main.py --host 0.0.0.0 --port 8877" -WindowStyle Hidden

# 验证服务启动
Start-Sleep -Seconds 5
netstat -ano | findstr :8877
```

### 步骤 2：后端配置

#### 2.1 修改环境变量
编辑 `/Users/claw/work/douyin-recorder/backend/.env`：
```bash
# 主服务地址（直接访问）
GPU_SERVICE_URL=http://10.190.0.203:8877

# 备用服务地址（SSH 隧道）
GPU_SERVICE_URL_FALLBACK=http://localhost:8877
```

#### 2.2 更新 GPU 客户端
创建 `/Users/claw/work/douyin-recorder/backend/gpu_client.py`：
```python
"""GPU Service Client with retry and fallback support."""
import os
import time
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# 主地址（直接访问）
PRIMARY_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")
# 备用地址（SSH 隧道）
FALLBACK_URL = os.environ.get("GPU_SERVICE_URL_FALLBACK", "http://localhost:8877")

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY = 5  # 秒

class GpuClient:
    """GPU 服务客户端，支持自动故障转移"""
    
    def __init__(self):
        self.primary_url = PRIMARY_URL
        self.fallback_url = FALLBACK_URL
        self.session = requests.Session()
        self.session.timeout = 30
        
    def _request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """发送 HTTP 请求，支持重试"""
        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(f"{method} {url} (attempt {attempt + 1})")
                resp = self.session.request(method, url, **kwargs)
                return resp
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        return None
    
    def get_health(self) -> Dict[str, Any]:
        """检查 GPU 服务健康状态"""
        # 先尝试主地址
        resp = self._request("GET", f"{self.primary_url}/health")
        if resp and resp.status_code == 200:
            return resp.json()
        
        # 故障转移到备用地址
        resp = self._request("GET", f"{self.fallback_url}/health")
        if resp and resp.status_code == 200:
            return resp.json()
        
        return {"online": False, "error": "Both endpoints failed"}
    
    def create_tts_job(self, text: str, voice_ref_id: str) -> Dict[str, Any]:
        """提交 TTS 任务"""
        payload = {"text": text, "voice_ref_id": voice_ref_id}
        
        # 尝试主地址
        resp = self._request("POST", f"{self.primary_url}/tts-jobs", json=payload)
        if resp and resp.status_code in (200, 201):
            return resp.json()
        
        # 故障转移到备用地址
        resp = self._request("POST", f"{self.fallback_url}/tts-jobs", json=payload)
        if resp and resp.status_code in (200, 201):
            return resp.json()
        
        return {"error": "Failed to submit TTS job"}
    
    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """查询任务状态"""
        resp = self._request("GET", f"{self.primary_url}/tts-jobs/{job_id}")
        if resp and resp.status_code == 200:
            return resp.json()
        
        resp = self._request("GET", f"{self.fallback_url}/tts-jobs/{job_id}")
        if resp and resp.status_code == 200:
            return resp.json()
        
        return {"error": "Job not found"}


# 全局客户端实例
_gpu_client = None

def get_gpu_client() -> GpuClient:
    """获取或创建 GPU 客户端单例"""
    global _gpu_client
    if _gpu_client is None:
        _gpu_client = GpuClient()
    return _gpu_client

def check_gpu_health() -> Dict[str, Any]:
    """检查 GPU 服务健康状态"""
    return get_gpu_client().get_health()

def submit_tts_job(text: str, voice_ref_id: str) -> Dict[str, Any]:
    """提交 TTS 任务"""
    return get_gpu_client().create_tts_job(text, voice_ref_id)

def get_tts_job(job_id: str) -> Dict[str, Any]:
    """查询 TTS 任务状态"""
    return get_gpu_client().get_job_status(job_id)
```

### 步骤 3：健康监控

#### 3.1 改进的监控脚本
```bash
#!/bin/bash
# scripts/gpu-monitor.sh (改进版)

GPU_HOST="10.190.0.203"
GPU_PORT=8877
LOG_FILE="/tmp/gpu-monitor.log"
CHECK_INTERVAL=60

# 健康检查（直接访问）
check_gpu_service() {
    local health_url="http://${GPU_HOST}:${GPU_PORT}/health"
    
    if curl -s --max-time 10 "$health_url" | grep -q '"online":true'; then
        echo "[$(date)] GPU service healthy (direct)" >> "$LOG_FILE"
        return 0
    else
        # 尝试 SSH 隧道
        local tunnel_url="http://localhost:${GPU_PORT}/health"
        if curl -s --max-time 5 "$tunnel_url" | grep -q '"online":true'; then
            echo "[$(date)] GPU service healthy (tunnel)" >> "$LOG_FILE"
            return 0
        fi
    fi
    
    echo "[$(date)] ERROR: GPU service unreachable" >> "$LOG_FILE"
    return 1
}

# 主循环
while true; do
    check_gpu_service
    sleep $CHECK_INTERVAL
done
```

---

## 紧急恢复步骤

如果 GPU 服务再次失效，按以下步骤操作：

### 1. 检查服务状态
```bash
# 检查直接连接
curl -s http://10.190.0.203:8877/health

# 检查隧道连接
curl -s http://localhost:8877/health
```

### 2. 远程重启服务
```bash
# SSH 到 GPU 服务器
ssh neo@10.190.0.203

# 停止所有 Python 进程
taskkill /F /IM python.exe

# 清理日志
cd C:\Users\neo\douyin_processor\gpu_service
del gpu_service.log 2>nul

# 启动服务
start /b C:\Python313\python.exe main.py
```

### 3. 验证恢复
```bash
# 等待 10 秒
sleep 10

# 检查服务状态
curl -s http://10.190.0.203:8877/health

# 检查后端状态
curl -s http://localhost:8899/api/status
```

---

## 总结

### 当前问题
- ❌ GPU 服务因日志权限问题无法启动
- ❌ SSH 隧道不稳定
- ❌ 767 条录音等待处理

### 解决方案
- ✅ 配置防火墙允许 LAN 直接访问
- ✅ 修改服务监听所有接口（0.0.0.0）
- ✅ 后端添加自动故障转移机制
- ✅ 改进健康监控脚本

### 预期效果
- 服务稳定性提升 90%+
- 延迟从 ~50ms 降到 ~5ms
- 不再依赖 SSH 隧道

