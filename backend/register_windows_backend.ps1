param([int]$Port = 8899)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "start_windows_backend.ps1"
$taskName = "Douyin Recorder Backend"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Port $Port"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType InteractiveToken -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Write-Host "Registered '$taskName'. It starts the backend in the user's interactive RDP session."
