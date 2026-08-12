# GPU 服务器物理访问操作手册

## 环境信息
- **服务器地址**: 10.190.0.203 (Windows)
- **SSH 用户**: neo
- **GPU 服务端口**: 8877 (TTS推理)
- **Watchdog 端口**: 8878 (健康监控)
- **Python 路径**: C:\Python313\python.exe
- **GPU 服务路径**: C:\Users\neo\douyin_processor\gpu_service\
- **监控服务器**: 10.190.0.176 (Mac Mini)

---

## 问题诊断

### 症状
- GPU 服务无法启动，提示日志权限错误：
  ```
  PermissionError: [Errno 13] Permission denied: 'C:\\Users\\neo\\AppData\\Local\\Temp\\gpu_service.log'
  ```
- 后端无法连接 GPU 服务
- SSH 远程命令返回空输出

### 可能原因
1. 日志文件被锁定（进程残留）
2. 目录权限问题
3. Windows 防火墙阻止连接
4. GPU 服务进程卡死

---

## 操作步骤

### 第一步：检查服务状态

打开 **PowerShell（管理员）**，执行：

```powershell
# 检查 GPU 服务进程
Write-Host "=== Python Processes ===" -ForegroundColor Cyan
tasklist /FI "IMAGENAME eq python.exe" /V

# 检查端口监听状态
Write-Host "`n=== Port 8877 Status ===" -ForegroundColor Cyan
netstat -ano | findstr :8877

# 检查端口监听状态
Write-Host "`n=== Port 8878 Status ===" -ForegroundColor Cyan
netstat -ano | findstr :8878

# 检查定时任务
Write-Host "`n=== Scheduled Tasks ===" -ForegroundColor Cyan
schtasks /query /tn GPU_Service /fo LIST /v
schtasks /query /tn GPU_Watchdog /fo LIST /v
```

**预期输出：**
- 如果有 Python 进程但端口未监听 → 进程卡死，需要终止
- 如果端口监听但无响应 → 服务崩溃，需要重启
- 如果没有进程 → 服务未启动，需要启动

---

### 第二步：终止残留进程

如果发现有 Python 进程：

```powershell
# 终止所有 Python 进程
Write-Host "`n=== Stopping Python Processes ===" -ForegroundColor Cyan
taskkill /F /IM python.exe
timeout /t 3 /nobreak

# 验证进程已终止
Write-Host "`n=== Verifying ===" -ForegroundColor Cyan
tasklist /FI "IMAGENAME eq python.exe"
```

**预期输出：**
```
成功: 已终止 PID <number> (属于 PID <parent>) 命令 C:\Python313\python.exe main.py
成功: 已终止 PID <number> (属于 PID <parent>) 命令 C:\Python313\python.exe watchdog_agent.py
```

---

### 第三步：清理日志文件

```powershell
# 清理旧日志
Write-Host "`n=== Cleaning Log Files ===" -ForegroundColor Cyan
cd C:\Users\neo\douyin_processor\gpu_service

# 删除旧日志
if (Test-Path gpu_service.log) {
    Remove-Item gpu_service.log -Force
    Write-Host "Deleted gpu_service.log"
}
if (Test-Path gpu_service_old.log) {
    Remove-Item gpu_service_old.log -Force
    Write-Host "Deleted gpu_service_old.log"
}

# 创建新日志目录
Write-Host "`n=== Creating Log Directory ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Path "C:\Temp\gpu_logs" -Force | Out-Null
Write-Host "Created C:\Temp\gpu_logs"

# 设置权限
Write-Host "`n=== Setting Permissions ===" -ForegroundColor Cyan
icacls "C:\Temp\gpu_logs" /grant neo:(F)
Write-Host "Permissions set"
```

---

### 第四步：启动 GPU 服务

#### 方式一：使用 PowerShell（推荐）

```powershell
# 启动 GPU 服务（后台运行）
Write-Host "`n=== Starting GPU Service ===" -ForegroundColor Cyan
$env:GPU_LOG_DIR = "C:\Temp\gpu_logs"
cd C:\Users\neo\douyin_processor\gpu_service

# 使用 Start-Process 启动（窗口最小化）
$process = Start-Process -FilePath "C:\Python313\python.exe" `
    -ArgumentList "main.py" `
    -WorkingDirectory "C:\Users\neo\douyin_processor\gpu_service" `
    -WindowStyle Minimized `
    -PassThru

Write-Host "Started GPU service with PID: $($process.Id)"
Start-Sleep -Seconds 5

# 验证服务启动
Write-Host "`n=== Verifying Service ===" -ForegroundColor Cyan
netstat -ano | findstr :8877
```

#### 方式二：使用 CMD（备用）

```cmd
:: 打开新的 CMD 窗口
start "" cmd /k "cd /d C:\Users\neo\douyin_processor\gpu_service && set GPU_LOG_DIR=C:\Temp\gpu_logs && C:\Python313\python.exe main.py"
```

---

### 第五步：验证服务启动

```powershell
# 等待服务启动
Write-Host "`n=== Waiting for Service ===" -ForegroundColor Cyan
Start-Sleep -Seconds 10

# 检查进程
Write-Host "`n=== Process Check ===" -ForegroundColor Cyan
tasklist /FI "IMAGENAME eq python.exe" /V

# 检查端口
Write-Host "`n=== Port Check ===" -ForegroundColor Cyan
netstat -ano | findstr :8877

# 检查健康状态
Write-Host "`n=== Health Check ===" -ForegroundColor Cyan
$health = Invoke-WebRequest -Uri "http://localhost:8877/health" -UseBasicParsing
$health.Content
```

**预期输出：**
```json
{
  "online": true,
  "gpu_available": true,
  "device_count": 1,
  "queue_depth": 0,
  "busy": false,
  "version": "v1.0.0",
  "message": "GPU service is running"
}
```

---

### 第六步：配置防火墙规则

```powershell
# 添加防火墙规则
Write-Host "`n=== Configuring Firewall ===" -ForegroundColor Cyan
netsh advfirewall firewall add rule name="GPU Service 8877" dir=in action=allow protocol=tcp localport=8877

# 验证规则
Write-Host "`n=== Verifying Firewall Rule ===" -ForegroundColor Cyan
netsh advfirewall firewall show rule name="GPU Service 8877"
```

**预期输出：**
```
规则名称: GPU Service 8877
-------------------------------------------------------------------
描述: GPU Service TTS 推理
方向: 入站
操作: 允许
本地地址: 任何
协议: TCP
本地端口: 8877
远程端口: 任何
远程地址: 任何
配置文件: 域,专用,公用
接口类型: 任何
状态: 已启用
```

---

### 第七步：启动 Watchdog（可选）

```powershell
# 启动 Watchdog 健康监控
Write-Host "`n=== Starting Watchdog ===" -ForegroundColor Cyan
$watchdog = Start-Process -FilePath "C:\Python313\python.exe" `
    -ArgumentList "watchdog_agent.py" `
    -WorkingDirectory "C:\Users\neo\douyin_processor" `
    -WindowStyle Minimized `
    -PassThru

Write-Host "Started watchdog with PID: $($watchdog.Id)"
Start-Sleep -Seconds 3

# 检查 Watchdog 端口
Write-Host "`n=== Watchdog Check ===" -ForegroundColor Cyan
netstat -ano | findstr :8878
```

---

### 第八步：测试 TTS 功能

```powershell
# 提交测试任务
Write-Host "`n=== Testing TTS ===" -ForegroundColor Cyan
$tts_payload = @{
    text = "这是一个测试文本"
    voice_ref_id = "default"
} | ConvertTo-Json

$headers = @{
    "Content-Type" = "application/json"
}

try {
    $response = Invoke-RestMethod -Uri "http://localhost:8877/tts-jobs" -Method POST -Body $tts_payload -ContentType "application/json" -TimeoutSec 10
    Write-Host "Job submitted: $($response.job_id)"
    Write-Host "Status: $($response.status)"
} catch {
    Write-Host "ERROR: $_"
}
```

---

### 第九步：验证后端连接

在监控服务器（Mac Mini）上执行：

```bash
# 检查后端状态
curl -s http://localhost:8899/api/status | python3 -m json.tool

# 测试 GPU 服务连接（通过 SSH 隧道或直接访问）
curl -s http://10.190.0.203:8877/health
```

**预期输出：**
```json
{
  "online": true,
  "gpu_available": true,
  "queue_depth": 0,
  "busy": false
}
```

---

## 故障排除

### 问题 1：服务启动失败，提示端口已被占用

```powershell
# 查找占用端口的进程
netstat -ano | findstr :8877

# 终止进程（替换 PID）
taskkill /F /PID <pid>
```

### 问题 2：服务启动后无法访问

```powershell
# 检查防火墙
Get-NetFirewallRule -DisplayName "*GPU*" | Select-Object DisplayName, Enabled, Direction, Action

# 临时关闭防火墙测试（仅用于诊断）
netsh advfirewall set allprofiles state off
# 测试后重新开启
netsh advfirewall set allprofiles state on
```

### 问题 3：GPU 未被识别

```powershell
# 检查 CUDA
& "C:\Python313\python.exe" -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'Device count: {torch.cuda.device_count()}')"

# 检查 NVIDIA 驱动
nvidia-smi
```

### 问题 4：日志权限错误

```powershell
# 清理所有日志文件
cd C:\Users\neo\douyin_processor\gpu_service
del *.log /F /Q

# 创建新日志目录并设置权限
New-Item -ItemType Directory -Path "C:\Temp\gpu_logs" -Force
icacls "C:\Temp\gpu_logs" /grant neo:(F)

# 设置环境变量
$env:GPU_LOG_DIR = "C:\Temp\gpu_logs"
```

### 问题 5：SSH 远程命令返回空输出

**原因：** 可能是 SSH 配置问题或权限问题

**解决方案：**
1. 使用物理访问或远程桌面
2. 检查 SSH 服务状态：`Get-Service sshd | Start-Service`
3. 检查 SSH 日志：`Get-Content C:\Windows\System32\LogFiles\SSHD\sshd.log -Tail 50`

---

## 启动脚本（一键执行）

创建文件 `C:\Users\neo\douyin_processor\start-gpu-service.ps1`：

```powershell
# GPU Service Startup Script
Write-Host "=== GPU Service Startup Script ===" -ForegroundColor Cyan

# 1. 停止所有 Python 进程
Write-Host "`n[1/5] Stopping existing processes..." -ForegroundColor Yellow
taskkill /F /IM python.exe 2>$null
Start-Sleep -Seconds 2

# 2. 清理日志
Write-Host "[2/5] Cleaning log files..." -ForegroundColor Yellow
cd C:\Users\neo\douyin_processor\gpu_service
del gpu_service.log 2>$null
del gpu_service_old.log 2>$null

# 3. 创建日志目录
Write-Host "[3/5] Creating log directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path "C:\Temp\gpu_logs" -Force | Out-Null

# 4. 启动 GPU 服务
Write-Host "[4/5] Starting GPU service..." -ForegroundColor Yellow
$env:GPU_LOG_DIR = "C:\Temp\gpu_logs"
Start-Process -FilePath "C:\Python313\python.exe" `
    -ArgumentList "main.py" `
    -WorkingDirectory "C:\Users\neo\douyin_processor\gpu_service" `
    -WindowStyle Minimized

Start-Sleep -Seconds 5

# 5. 验证启动
Write-Host "[5/5] Verifying..." -ForegroundColor Yellow
$health = Invoke-WebRequest -Uri "http://localhost:8877/health" -UseBasicParsing -TimeoutSec 5
if ($health.StatusCode -eq 200) {
    Write-Host "`n✓ GPU service started successfully!" -ForegroundColor Green
    $health.Content
} else {
    Write-Host "`n✗ GPU service failed to start" -ForegroundColor Red
}
```

运行方式：
```powershell
# 以管理员身份运行
.\start-gpu-service.ps1
```

---

## 验证清单

服务启动后，确认以下项目：

- [ ] Python 进程运行中（`tasklist | findstr python`）
- [ ] 端口 8877 监听中（`netstat -ano | findstr :8877`）
- [ ] 健康检查返回 `{"online": true}`（`curl http://localhost:8877/health`）
- [ ] GPU 被识别（`torch.cuda.is_available() == True`）
- [ ] 防火墙规则已创建（`netsh advfirewall firewall show rule name="GPU Service 8877"`）
- [ ] 后端可以访问 GPU 服务（从监控服务器 `curl http://10.190.0.203:8877/health`）
- [ ] TTS 测试任务成功提交（`curl -X POST http://localhost:8877/tts-jobs`）

---

## 后续维护

### 定期检查服务状态

```powershell
# 添加到计划任务，每小时检查一次
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File C:\Users\neo\douyin_processor\check-gpu-service.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "GPU_Service_Monitor" -Action $action -Trigger $trigger -RunLevel Highest
```

### 查看服务日志

```powershell
# 实时查看日志
Get-Content C:\Users\neo\douyin_processor\gpu_service\gpu_service.log -Wait
```

---

## 联系信息

如有问题，请联系：
- 运维团队：neo@10.190.0.203
- 监控服务器：10.190.0.176

---

**文档版本**: 1.0
**最后更新**: 2026-08-11
**适用环境**: Windows Server (GPU 推理服务)
