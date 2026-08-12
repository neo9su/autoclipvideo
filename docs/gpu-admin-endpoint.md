# GPU 服务管理端点

## 问题
GPU 服务经常意外停止，需要通过 SSH 手动恢复。

## 解决方案
为 GPU 服务添加 HTTP 管理端点，通过 HTTP POST 触发重启。

## 实现方式

### 1. 在 gpu_service/main.py 中添加管理路由

```python
from fastapi import FastAPI
import subprocess
import os

@app.post("/admin/restart")
async def restart_service():
    """重启 GPU 服务"""
    # 获取当前进程
    current_pid = os.getpid()
    
    # 启动新进程
    subprocess.Popen(
        [sys.executable, "-m", "gpu_service.main"],
        stdout=open(r"C:\Temp\gpu.out.log", "w"),
        stderr=open(r"C:\Temp\gpu.err.log", "w"),
        cwd=r"C:\Users\neo\douyin_processor"
    )
    
    # 停止当前进程
    os._exit(0)
    
    return {"status": "restarting"}

@app.get("/admin/health")
async def admin_health():
    """健康检查"""
    return {
        "status": "ok",
        "pid": os.getpid(),
        "uptime": time.time() - start_time
    }
```

### 2. 使用方式

```bash
# 重启 GPU 服务
curl -X POST http://10.190.0.203:8877/admin/restart

# 检查健康状态
curl http://10.190.0.203:8877/admin/health
```

### 3. 防火墙配置

确保端口 8877 和 9999 已对外开放：
```powershell
# 检查防火墙规则
netsh advfirewall firewall show rule name=all | findstr "8877"
netsh advfirewall firewall show rule name=all | findstr "9999"

# 添加规则（如果不存在）
netsh advfirewall firewall add rule name="GPU Service 8877" dir=in action=allow protocol=tcp localport=8877
netsh advfirewall firewall add rule name="GPU Admin 9999" dir=in action=allow protocol=tcp localport=9999
```

## 优势
- 无需 SSH 即可恢复服务
- 可以通过 cron 定时检查
- 集成到监控系统中
