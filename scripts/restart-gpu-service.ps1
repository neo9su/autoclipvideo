# GPU Service Restart Script
$WorkDir = "C:\Users\neo\douyin_processor"
$Python = "C:\Python313\python.exe"

Write-Host "=== GPU Service Restart ===" -ForegroundColor Cyan

# Kill existing processes
Write-Host "Stopping existing Python processes..."
Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

# Clear port 8877 if stuck
$tcp = Get-NetTCPConnection -LocalPort 8877 -ErrorAction SilentlyContinue
if ($tcp) {
    Write-Host "Killing process on port 8877: $($tcp.OwningProcess)"
    Stop-Process -Id $tcp.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Start service
Write-Host "Starting GPU service..."
cd $WorkDir
Start-Process -FilePath $Python -ArgumentList "-m", "gpu_service.main" -WorkingDirectory $WorkDir -WindowStyle Hidden

# Wait for startup
Write-Host "Waiting for service to start..."
$tries = 0
while ($tries -lt 20) {
    Start-Sleep -Seconds 3
    $response = Invoke-WebRequest -Uri "http://localhost:8877/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($response) {
        Write-Host "Service started successfully!" -ForegroundColor Green
        Write-Host $response.Content
        exit 0
    }
    $tries++
}

Write-Host "Service failed to start within 60 seconds" -ForegroundColor Red
exit 1
