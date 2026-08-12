# GPU Service Verification Script

Write-Host "=== GPU Service Verification ===" -ForegroundColor Cyan

# 检查进程
Write-Host "`n[1] Process Check" -ForegroundColor Yellow
$python = Get-Process -Name "python" -ErrorAction SilentlyContinue
if ($python) {
    Write-Host "  Python processes running:" -ForegroundColor Green
    $python | Select-Object Id, StartTime, @{Name="Memory(MB)";Expression={[math]::Round($_.WorkingSet64/1MB,2)}} | Format-Table -AutoSize
} else {
    Write-Host "  No Python processes found" -ForegroundColor Red
}

# 检查端口
Write-Host "`n[2] Port Check" -ForegroundColor Yellow
$port8877 = netstat -ano | findstr ":8877.*LISTENING"
$port8878 = netstat -ano | findstr ":8878.*LISTENING"

if ($port8877) {
    Write-Host "  Port 8877 listening" -ForegroundColor Green
    Write-Host "    $port8877"
} else {
    Write-Host "  Port 8877 not listening" -ForegroundColor Red
}

if ($port8878) {
    Write-Host "  Port 8878 listening (watchdog)" -ForegroundColor Green
    Write-Host "    $port8878"
} else {
    Write-Host "  Port 8878 not listening (optional)" -ForegroundColor Yellow
}

# 检查健康状态
Write-Host "`n[3] Health Check" -ForegroundColor Yellow
try {
    $health = Invoke-WebRequest -Uri "http://localhost:8877/health" -UseBasicParsing -TimeoutSec 5
    $json = $health.Content | ConvertFrom-Json
    if ($json.online) {
        Write-Host "  GPU service is healthy" -ForegroundColor Green
        Write-Host "    Online: $($json.online)"
        Write-Host "    GPU Available: $($json.gpu_available)"
        Write-Host "    Queue Depth: $($json.queue_depth)"
        Write-Host "    Busy: $($json.busy)"
    } else {
        Write-Host "  GPU service reports offline" -ForegroundColor Red
    }
} catch {
    Write-Host "  Cannot reach GPU service: $_" -ForegroundColor Red
}

# 检查防火墙
Write-Host "`n[4] Firewall Check" -ForegroundColor Yellow
$rule = Get-NetFirewallRule -DisplayName "*GPU*" -ErrorAction SilentlyContinue
if ($rule) {
    Write-Host "  Firewall rule found:" -ForegroundColor Green
    $rule | Select-Object DisplayName, Enabled, Direction, Action | Format-Table -AutoSize
} else {
    Write-Host "  No firewall rule found (service may still work)" -ForegroundColor Yellow
}

# 检查日志
Write-Host "`n[5] Log Check" -ForegroundColor Yellow
$logPath = "C:\Users\neo\douyin_processor\gpu_service\gpu_service.log"
if (Test-Path $logPath) {
    $size = (Get-Item $logPath).Length
    Write-Host "  Log file exists: $logPath ($([math]::Round($size/1KB,2)) KB)" -ForegroundColor Green
    Write-Host "  Last 5 lines:"
    Get-Content $logPath -Tail 5 | ForEach-Object { Write-Host "    $_" }
} else {
    Write-Host "  Log file not found (may be using alternative path)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Verification Complete ===" -ForegroundColor Cyan
