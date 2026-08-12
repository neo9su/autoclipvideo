# Douyin Services Cleanup & Setup Script
# Run this on the server to fix service conflicts

Write-Host "=== Douyin Services Setup ===" -ForegroundColor Cyan

# 1. Disable ALL conflicting tasks
Write-Host "`n[1/4] Disabling conflicting scheduled tasks..." -ForegroundColor Yellow
$tasksToDisable = @(
    "\GPU_Service",
    "\StartGPUSvc",
    "\WatchdogAgent",
    "\WatchdogNow",
    "\StartWatchdog",
    "\OpenClawWatchdogRuntime",
    "\OpenClawRecoverWatchdog",
    "\DouyinRemoteBackend8899",
    "\DouyinRemoteBackend8899Interactive"
)

foreach ($task in $tasksToDisable) {
    try {
        schtasks /change /tn $task /disable 2>$null
        Write-Host "  Disabled: $task" -ForegroundColor Gray
    } catch {
        Write-Host "  Skip: $task (not found)" -ForegroundColor Gray
    }
}

# 2. Keep only essential tasks enabled
Write-Host "`n[2/4] Enabling essential tasks..." -ForegroundColor Yellow
$essentialTasks = @(
    "\DouyinBackend",
    "\DouyinGPUServices",
    "\DouyinWatchdogAgent_Fixed"
)

foreach ($task in $essentialTasks) {
    try {
        schtasks /change /tn $task /enable 2>$null
        Write-Host "  Enabled: $task" -ForegroundColor Green
    } catch {
        Write-Host "  Skip: $task" -ForegroundColor Gray
    }
}

# 3. Kill existing processes
Write-Host "`n[3/4] Cleaning up processes..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $PID } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Host "  Python processes cleaned" -ForegroundColor Gray

# 4. Start services in correct order
Write-Host "`n[4/4] Starting services..." -ForegroundColor Yellow

# Start GPU Service first (no dependencies)
Write-Host "  Starting GPU Service..." -ForegroundColor Cyan
Start-Process -FilePath "C:\Python313\python.exe" `
    -ArgumentList "-u", "C:\Users\neo\douyin_processor\gpu_service.py" `
    -WorkingDirectory "C:\Users\neo\douyin_processor" `
    -RedirectStandardOutput "C:\Users\neo\douyin_processor\gpu_out.log" `
    -RedirectStandardError "C:\Users\neo\douyin_processor\gpu_err.log" `
    -WindowStyle Hidden `
    -Wait:$false

Start-Sleep -Seconds 3

# Start Watchdog (monitors GPU + Backend)
Write-Host "  Starting Watchdog..." -ForegroundColor Cyan
Start-Process -FilePath "C:\Python313\python.exe" `
    -ArgumentList "-u", "C:\Users\neo\douyin_processor\watchdog_agent.py" `
    -WorkingDirectory "C:\Users\neo\douyin_processor" `
    -RedirectStandardOutput "C:\Users\neo\douyin_processor\watchdog_out.log" `
    -RedirectStandardError "C:\Users\neo\douyin_processor\watchdog_err.log" `
    -WindowStyle Hidden `
    -Wait:$false

Start-Sleep -Seconds 3

# Verify services
Write-Host "`n=== Verification ===" -ForegroundColor Cyan

$gpuHealth = try { (Invoke-WebRequest -Uri "http://localhost:8877/health" -TimeoutSec 5).Content | ConvertFrom-Json } catch { $null }
if ($gpuHealth) {
    Write-Host "  GPU Service: ONLINE (PID: $($gpuHealth.pid))" -ForegroundColor Green
} else {
    Write-Host "  GPU Service: OFFLINE" -ForegroundColor Red
}

$watchdogHealth = try { (Invoke-WebRequest -Uri "http://localhost:8878/health" -TimeoutSec 5).Content | ConvertFrom-Json } catch { $null }
if ($watchdogHealth) {
    Write-Host "  Watchdog: ONLINE" -ForegroundColor Green
} else {
    Write-Host "  Watchdog: OFFLINE (will start via scheduled task)" -ForegroundColor Yellow
}

$backendHealth = try { (Invoke-WebRequest -Uri "http://localhost:8899/api/monitor/status" -TimeoutSec 5).Content | ConvertFrom-Json } catch { $null }
if ($backendHealth) {
    Write-Host "  Backend: ONLINE (rooms: $($backendHealth.rooms.enabled))" -ForegroundColor Green
} else {
    Write-Host "  Backend: OFFLINE" -ForegroundColor Red
}

Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "Logs: C:\Users\neo\douyin_processor\*.log" -ForegroundColor Gray
