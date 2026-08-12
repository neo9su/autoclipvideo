# Script to start backend and GPU service
Write-Host "Starting Douyin Backend..."
Start-Process -FilePath "C:\Python313\python.exe" -ArgumentList "-m","uvicorn","main:app","--host","0.0.0.0","--port","8899","--app-dir","C:\Users\neo\douyin_backend\backend" -WindowStyle Hidden -WorkingDirectory "C:\Users\neo\douyin_backend\backend"
Start-Sleep -Seconds 3

Write-Host "Starting GPU Service..."
Start-Process -FilePath "C:\Python313\python.exe" -ArgumentList "-m","uvicorn","main:app","--host","0.0.0.0","--port","8877","--app-dir","C:\Users\neo\gpu_service" -WindowStyle Hidden -WorkingDirectory "C:\Users\neo\gpu_service"
Start-Sleep -Seconds 3

Write-Host "Checking services..."
$backend = netstat -ano | findstr ":8899"
$gpu = netstat -ano | findstr ":8877"

if ($backend) {
    Write-Host "Backend: OK"
} else {
    Write-Host "Backend: FAILED"
}

if ($gpu) {
    Write-Host "GPU Service: OK"
} else {
    Write-Host "GPU Service: FAILED"
}

Write-Host "Done. PID:"
Get-Process python* -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $($_.Id) $($_.StartTime)" }
