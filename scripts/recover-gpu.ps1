# GPU Service Recovery Script
$WorkDir = "C:\Users\neo\douyin_processor"
$Python = "C:\Python313\python.exe"

Write-Host "=== GPU Service Recovery ===" -ForegroundColor Cyan

# Step 1: Kill existing processes
Write-Host "Step 1: Stopping Python processes..."
Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# Step 2: Wait for port to be free
Write-Host "Step 2: Waiting for port 8877..."
for ($i=0; $i -lt 10; $i++) {
    $tcp = Get-NetTCPConnection -LocalPort 8877 -ErrorAction SilentlyContinue
    if (-not $tcp) { break }
    Write-Host "  Port still in use, waiting..."
    Start-Sleep -Seconds 1
}

# Step 3: Start service
Write-Host "Step 3: Starting GPU service..."
Set-Location $WorkDir
$proc = Start-Process -FilePath $Python -ArgumentList "-m", "gpu_service.main" -WorkingDirectory $WorkDir -PassThru -WindowStyle Hidden
Write-Host "  PID: $($proc.Id)"

# Step 4: Wait and verify
Write-Host "Step 4: Verifying service..."
for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:8877/health" -TimeoutSec 3
        Write-Host "Service healthy!" -ForegroundColor Green
        Write-Host $resp | ConvertTo-Json
        exit 0
    } catch {
        Write-Host "  Waiting... ($($i+1)/20)"
    }
}

Write-Host "Service failed to start" -ForegroundColor Red
exit 1
