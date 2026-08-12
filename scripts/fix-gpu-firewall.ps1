# GPU 服务器防火墙和服务配置修复脚本
# 运行方式: ssh neo@10.190.0.203 "powershell -ExecutionPolicy Bypass -File fix-gpu-firewall.ps1"

Write-Host "=== GPU Service Network Configuration ===" -ForegroundColor Cyan

# 1. 停止 GPU 服务
Write-Host "Stopping GPU service..." -ForegroundColor Yellow
Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# 2. 修改服务配置文件，让它监听所有接口
$serviceConfigPath = "C:\Users\neo\douyin_processor\gpu_service\config.json"
if (Test-Path $serviceConfigPath) {
    $config = Get-Content $serviceConfigPath | ConvertFrom-Json
    $config.host = "0.0.0.0"
    $config.port = 8877
    $config | ConvertTo-Json | Set-Content $serviceConfigPath
    Write-Host "Updated config.json" -ForegroundColor Green
} else {
    Write-Host "No config.json found, will add host parameter" -ForegroundColor Yellow
}

# 3. 创建防火墙规则
Write-Host "Creating firewall rule..." -ForegroundColor Yellow
try {
    $existingRule = Get-NetFirewallRule -DisplayName "GPU Service 8877" -ErrorAction SilentlyContinue
    if ($existingRule) {
        Remove-NetFirewallRule -DisplayName "GPU Service 8877" -Confirm:$false
    }
    New-NetFirewallRule -DisplayName "GPU Service 8877" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 8877 `
        -Action Allow `
        -Profile Private,Domain `
        -ErrorAction Stop
    Write-Host "Firewall rule created" -ForegroundColor Green
} catch {
    Write-Host "Firewall rule creation failed: $_" -ForegroundColor Red
}

# 4. 创建启动脚本
$startScript = @'
cd C:\Users\neo\douyin_processor\gpu_service
$env:GPU_LOG_DIR = "C:\Temp\gpu_logs"
if (!(Test-Path $env:GPU_LOG_DIR)) { New-Item -ItemType Directory -Path $env:GPU_LOG_DIR -Force }
Start-Process -FilePath "C:\Python313\python.exe" -ArgumentList "main.py --host 0.0.0.0 --port 8877" -WindowStyle Hidden
'@

$startScript | Set-Content "C:\Users\neo\douyin_processor\start_gpu_service.ps1" -Encoding UTF8
Write-Host "Created start script" -ForegroundColor Green

# 5. 启动服务
Write-Host "Starting GPU service..." -ForegroundColor Yellow
& "C:\Users\neo\douyin_processor\start_gpu_service.ps1"
Start-Sleep -Seconds 10

# 6. 验证
Write-Host "=== Verification ===" -ForegroundColor Cyan
Write-Host "Process:"
Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime

Write-Host "Listening ports:"
netstat -ano | Select-String ":8877.*LISTENING"

Write-Host "Firewall rules:"
Get-NetFirewallRule -DisplayName "GPU Service 8877" | Select-Object DisplayName, Enabled, Direction, Action
