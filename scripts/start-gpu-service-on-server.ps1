# GPU Service Startup Script
# 复制到 GPU 服务器后运行：C:\Users\neo\douyin_processor\start-gpu-service.ps1

Write-Host "=== GPU Service Startup Script ===" -ForegroundColor Cyan
Write-Host "Target: 10.190.0.203" -ForegroundColor Cyan
Write-Host ""

# 1. 停止所有 Python 进程
Write-Host "[1/5] Stopping existing processes..." -ForegroundColor Yellow
taskkill /F /IM python.exe 2>$null
timeout /t 2 /nobreak

# 2. 清理日志
Write-Host "[2/5] Cleaning log files..." -ForegroundColor Yellow
cd C:\Users\neo\douyin_processor\gpu_service
del gpu_service.log 2>$null
del gpu_service_old.log 2>$null

# 3. 创建日志目录
Write-Host "[3/5] Creating log directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path "C:\Temp\gpu_logs" -Force | Out-Null
icacls "C:\Temp\gpu_logs" /grant neo:(F) 2>$null

# 4. 启动 GPU 服务
Write-Host "[4/5] Starting GPU service..." -ForegroundColor Yellow
$env:GPU_LOG_DIR = "C:\Temp\gpu_logs"
Start-Process -FilePath "C:\Python313\python.exe" `
    -ArgumentList "main.py" `
    -WorkingDirectory "C:\Users\neo\douyin_processor\gpu_service" `
    -WindowStyle Minimized

timeout /t 5 /nobreak

# 5. 验证启动
Write-Host "[5/5] Verifying..." -ForegroundColor Yellow
try {
    $health = Invoke-WebRequest -Uri "http://localhost:8877/health" -UseBasicParsing -TimeoutSec 5
    if ($health.StatusCode -eq 200) {
        Write-Host ""
        Write-Host "✓ GPU service started successfully!" -ForegroundColor Green
        Write-Host $health.Content
    } else {
        Write-Host ""
        Write-Host "✗ GPU service failed to start (HTTP $($health.StatusCode))" -ForegroundColor Red
    }
} catch {
    Write-Host ""
    Write-Host "✗ GPU service failed to start: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Verification ===" -ForegroundColor Cyan
Write-Host "Process check:"
tasklist /FI "IMAGENAME eq python.exe" /V
Write-Host ""
Write-Host "Port check:"
netstat -ano | findstr :8877
Write-Host ""
Write-Host "Health check:"
curl -s http://localhost:8877/health 2>$null || Write-Host "Service not reachable"
