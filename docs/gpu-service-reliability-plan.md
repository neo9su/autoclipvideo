# GPU 服务可靠性改进方案

## 当前问题分析

### 1. GPU 服务频繁失效
- **根本原因**：日志文件权限问题 `PermissionError: [Errno 13] Permission denied`
- **症状**：服务无法启动，端口 8877 无响应
- **影响**：所有 TTS、视频剪辑任务停滞

### 2. SSH 隧道不稳定
- SSH 隧道断开后自动重连，但 GPU 服务不会自动重启
- 需要人工介入才能恢复

### 3. 网络架构问题
- GPU 服务仅在 Windows 任务调度器中运行
- 没有看门狗进程监控服务状态
- 日志文件锁定导致服务无法启动

---

## 解决方案

### 方案一：改进 GPU 服务自身（推荐）

#### 1.1 修复日志权限问题
```python
# gpu_service/logging_setup.py
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler

def configure_logging(name, log_file=None, default_directory=None):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # 始终添加控制台输出（stderr）
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logger.addHandler(console)
    
    # 文件日志使用更安全的配置
    if log_file and default_directory:
        try:
            # 使用环境变量指定日志目录
            log_dir = os.environ.get('GPU_LOG_DIR', default_directory)
            log_path = Path(log_dir) / log_file
            
            # 确保目录存在
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            handler = RotatingFileHandler(
                str(log_path),
                maxBytes=5*1024*1024,  # 5MB
                backupCount=2,
                encoding='utf-8',
            )
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            logger.addHandler(handler)
        except Exception as e:
            print(f"Warning: Log file error: {e}")
    
    return logger
```

#### 1.2 添加内置看门狗
```python
# gpu_service/main.py
import threading
import time
import signal
import sys

class ServiceWatchdog:
    """内置看门狗：监控服务健康状态"""
    
    def __init__(self, check_interval=30, restart_delay=60):
        self.check_interval = check_interval
        self.restart_delay = restart_delay
        self.last_check_time = 0
        self.consecutive_failures = 0
        self.running = True
        
    def check_health(self):
        """检查服务健康状态"""
        try:
            # 尝试访问健康端点
            import urllib.request
            req = urllib.request.Request('http://localhost:8877/health')
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    self.consecutive_failures = 0
                    return True
        except Exception as e:
            self.consecutive_failures += 1
            print(f"Health check failed: {e}")
            
        return False
    
    def run(self):
        """看门狗主循环"""
        while self.running:
            time.sleep(self.check_interval)
            if not self.check_health():
                if self.consecutive_failures >= 3:
                    print("Service unhealthy after 3 checks, attempting restart...")
                    self.restart_service()
    
    def restart_service(self):
        """重启服务"""
        # 这里可以实现优雅的重启逻辑
        pass

# 启动看门狗
watchdog = ServiceWatchdog(check_interval=30, restart_delay=60)
watchdog_thread = threading.Thread(target=watchdog.run, daemon=True)
watchdog_thread.start()
```

---

### 方案二：独立的健康监控服务

#### 2.1 在 GPU 服务器上创建健康检查服务
```python
# gpu_service/health_monitor.py
import asyncio
import aiohttp
import logging
import subprocess
import sys
from datetime import datetime

logger = logging.getLogger('health_monitor')

class GPUHealthMonitor:
    """GPU 服务健康监控"""
    
    def __init__(self):
        self.service_url = "http://localhost:8877/health"
        self.check_interval = 30  # 秒
        self.max_restarts = 3
        self.restart_count = 0
        
    async def check_health(self):
        """检查服务健康状态"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.service_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def restart_service(self):
        """重启 GPU 服务"""
        logger.info("Attempting to restart GPU service...")
        try:
            # 停止所有 Python 进程
            subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], capture_output=True)
            await asyncio.sleep(5)
            
            # 启动新进程
            proc = subprocess.Popen([
                sys.executable, 'main.py',
                '--log-dir', 'C:/Temp/gpu_logs'
            ], cwd='C:/Users/neo/douyin_processor/gpu_service')
            
            self.restart_count += 1
            logger.info(f"GPU service restarted (attempt {self.restart_count})")
            return True
        except Exception as e:
            logger.error(f"Restart failed: {e}")
            return False
    
    async def run(self):
        """主监控循环"""
        logger.info("GPU Health Monitor started")
        
        while True:
            healthy = await self.check_health()
            
            if not healthy:
                logger.warning(f"GPU service unhealthy, restart count: {self.restart_count}")
                if self.restart_count < self.max_restarts:
                    await self.restart_service()
                    await asyncio.sleep(60)  # 等待服务启动
                else:
                    logger.error("Max restart attempts reached, stopping monitor")
                    break
            else:
                self.restart_count = 0
            
            await asyncio.sleep(self.check_interval)

if __name__ == '__main__':
    asyncio.run(GPUHealthMonitor().run())
```

#### 2.2 创建 Windows 任务调度器条目
```powershell
# 创建健康监控服务任务
$action = New-ScheduledTaskAction -Execute "C:\Python313\python.exe" -Argument "C:\Users\neo\douyin_processor\gpu_service\health_monitor.py"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "neo" -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "GPU_Health_Monitor" -Action $action -Trigger $trigger -Principal $principal -Settings $settings
```

---

### 方案三：改进 SSH 隧道和监控

#### 3.1 改进 SSH 隧道脚本
```bash
#!/bin/bash
# scripts/gpu-monitor.sh (改进版)

GPU_HOST="10.190.0.203"
GPU_USER="neo"
LOCAL_PORT=8877
REMOTE_PORT=8877
LOG_FILE="/tmp/gpu-monitor.log"
TUNNEL_CMD="ssh -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -N -f -L ${LOCAL_PORT}:${GPU_HOST}:${REMOTE_PORT} ${GPU_USER}@${GPU_HOST}"

# 启动或重启 SSH 隧道
start_tunnel() {
    echo "[$(date)] Starting SSH tunnel..." >> "$LOG_FILE"
    $TUNNEL_CMD
}

# 停止 SSH 隧道
stop_tunnel() {
    pkill -f "ssh.*${GPU_HOST}.*${LOCAL_PORT}"
}

# 检查 GPU 服务状态
check_gpu_service() {
    local health_url="http://localhost:${LOCAL_PORT}/health"
    
    if curl -s --max-time 5 "$health_url" | grep -q '"online":true'; then
        echo "[$(date)] GPU service healthy" >> "$LOG_FILE"
        return 0
    else
        echo "[$(date)] GPU service unhealthy" >> "$LOG_FILE"
        return 1
    fi
}

# 远程重启 GPU 服务
restart_gpu_service() {
    echo "[$(date)] Attempting to restart GPU service..." >> "$LOG_FILE"
    
    ssh -o ConnectTimeout=10 "${GPU_USER}@${GPU_HOST}" "
        taskkill /F /IM python.exe 2>nul
        timeout 5
        cd C:\\Users\\neo\\douyin_processor\\gpu_service
        start /b C:\\Python313\\python.exe main.py
    "
    
    sleep 15
    check_gpu_service
}

# 主循环
while true; do
    # 检查隧道状态
    if ! check_gpu_service; then
        # 隧道断开，尝试重连
        stop_tunnel
        sleep 5
        start_tunnel
        sleep 10
        
        # 再次检查
        if ! check_gpu_service; then
            # 尝试远程重启
            restart_gpu_service
        fi
    fi
    
    sleep 60
done
```

---

### 方案四：LAN 直接访问（最佳方案）

#### 4.1 配置 GPU 服务监听所有接口
```python
# gpu_service/main.py
if __name__ == '__main__':
    # 修改为监听所有接口
    app.run(host='0.0.0.0', port=8877)
```

#### 4.2 配置防火墙规则
```powershell
# 允许 8877 端口入站
New-NetFirewallRule -DisplayName "GPU Service 8877" -Direction Inbound -Protocol TCP -LocalPort 8877 -Action Allow
```

#### 4.3 修改后端配置
```python
# backend/.env
GPU_SERVICE_URL=http://10.190.0.203:8877  # 直接访问，无需 SSH 隧道
```

#### 4.4 创建独立的 API 代理服务
```python
# gpu_proxy.py - 在 GPU 服务器上运行
from fastapi import FastAPI
import aiohttp
import asyncio
import logging

app = FastAPI()
logger = logging.getLogger('gpu_proxy')

# GPU 服务 URL
GPU_SERVICE_URL = "http://localhost:8877"

@app.get("/health")
async def health():
    """健康检查"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{GPU_SERVICE_URL}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return await resp.json()
    except Exception as e:
        return {"online": False, "error": str(e)}

@app.post("/tts-jobs")
async def create_tts_job(job: dict):
    """转发 TTS 请求"""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{GPU_SERVICE_URL}/tts-jobs", json=job) as resp:
            return await resp.json()

# 运行代理
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8877)
```

---

## 实施建议

### 短期（立即）
1. 修复日志文件权限问题
2. 添加看门狗进程监控 GPU 服务
3. 改进 SSH 隧道脚本的自动重连逻辑

### 中期（本周）
1. 配置 GPU 服务监听所有接口
2. 设置防火墙规则允许 LAN 访问
3. 修改后端配置直接访问 GPU 服务

### 长期（下周）
1. 创建独立的 API 代理服务
2. 实现服务自动故障转移
3. 添加监控告警系统

---

## 紧急恢复步骤

如果 GPU 服务再次失效，按以下步骤操作：

1. SSH 到 GPU 服务器：
   ```bash
   ssh neo@10.190.0.203
   ```

2. 停止所有 Python 进程：
   ```powershell
   taskkill /F /IM python.exe
   ```

3. 清理日志文件：
   ```powershell
   cd C:\Users\neo\douyin_processor\gpu_service
   del gpu_service.log
   ren gpu_service_old.log gpu_service_old_backup.log 2>nul
   ```

4. 创建新日志目录：
   ```powershell
   mkdir C:\Temp\gpu_logs
   ```

5. 启动服务：
   ```powershell
   cd C:\Users\neo\douyin_processor\gpu_service
   set GPU_LOG_DIR=C:\Temp\gpu_logs
   start /b C:\Python313\python.exe main.py
   ```

6. 验证服务状态：
   ```bash
   # 在本机
   curl http://localhost:8877/health
   ```

---

## 总结

**是否必须依赖 SSH 隧道？**
- 是的，当前架构依赖 SSH 隧道来访问 GPU 服务
- 但如果配置 LAN 直接访问，就可以不依赖 SSH 隧道

**GPU 服务能否自启动？**
- 可以，通过 Windows 任务调度器
- 但需要添加看门狗来监控服务健康状态

**推荐使用方案四（LAN 直接访问）**，这样可以：
1. 消除 SSH 隧道依赖
2. 减少单点故障
3. 提高服务稳定性
4. 简化运维复杂度

