# 安装 GPU Admin Server 为 Windows 服务
$ScriptPath = "C:\Users\neo\douyin_processor\gpu-admin.py"
$ServiceName = "GpuAdmin"

Write-Host "=== 安装 GPU Admin 服务 ===" -ForegroundColor Cyan

# 检查是否已存在
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "服务已存在，停止并删除..."
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Remove-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
}

# 创建服务
Write-Host "创建 Windows 服务..."
$pythonPath = "C:\Python313\python.exe"
$serviceCommand = "& '$pythonPath' '$ScriptPath'"

# 使用 nssm 或 sc 命令
sc.exe create $ServiceName binPath= "$pythonPath -m gpu_admin" start= auto
if ($LASTEXITCODE -eq 0) {
    Write-Host "服务创建成功" -ForegroundColor Green
    sc.exe start $ServiceName
    Write-Host "服务已启动" -ForegroundColor Green
} else {
    Write-Host "服务创建失败，错误码: $LASTEXITCODE" -ForegroundColor Red
}
