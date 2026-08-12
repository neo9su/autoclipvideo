# Windows PowerShell startup script for GPU Service
# Run this to start the GPU service as a background process

$ErrorActionPreference = "Stop"

$scriptPath = "C:\Users\neo\douyin_processor"
$logPath = "C:\Temp\gpu_logs\startup.log"

# Create log directory if not exists
if (-not (Test-Path "C:\Temp\gpu_logs")) {
    New-Item -ItemType Directory -Path "C:\Temp\gpu_logs" -Force | Out-Null
}

# Check if already running
$existing = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*gpu_service*" }
if ($existing) {
    Write-Host "GPU Service already running (PID $($existing.Id))"
    exit 0
}

# Start as background process
Write-Host "Starting GPU Service..."
$proc = Start-Process -FilePath "python" -ArgumentList "-m", "gpu_service.main" -WorkingDirectory $scriptPath -PassThru -WindowStyle Hidden
Write-Host "GPU Service started with PID $($proc.Id)"
Write-Host "$(Get-Date) GPU Service started PID=$($proc.Id)" | Out-File -Append -FilePath $logPath

# Wait for service to be ready
Write-Host "Waiting for service to be ready..."
$retries = 0
while ($retries -lt 30) {
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:8877/health" -TimeoutSec 2 -ErrorAction Stop
        if ($response.status -eq "ok") {
            Write-Host "GPU Service is healthy! (jobs=$($response.jobs), cuda=$($response.cuda.available))"
            Write-Host "$(Get-Date) GPU Service healthy" | Out-File -Append -FilePath $logPath
            exit 0
        }
    } catch {}
    Start-Sleep -Seconds 1
    $retries++
}

Write-Host "WARNING: Service did not become ready in 30 seconds"
exit 1
