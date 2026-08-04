[CmdletBinding(SupportsShouldProcess)]
param([switch]$Apply, [string]$BackupDirectory = "$PSScriptRoot\task-backups")
$ErrorActionPreference = "Stop"
$canonical = @("DouyinGPU-Watchdog", "DouyinGPU-GPUService", "DouyinGPU-ComfyUI")
$knownDuplicates = @("GPUService", "DouyinGPUServices", "DouyinGPUServices_Boot", "StartGPUSvc")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $BackupDirectory $timestamp
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Write-Host "Exporting complete Task Scheduler inventory to $backup"
schtasks.exe /query /fo LIST /v | Out-File (Join-Path $backup "all-tasks.txt") -Encoding utf8
foreach ($name in ($canonical + $knownDuplicates)) {
    $xmlPath = Join-Path $backup (($name -replace '[\\/:*?"<>|]', '_') + ".xml")
    schtasks.exe /query /tn $name /xml 2>$null | Out-File $xmlPath -Encoding utf8
}
Write-Host "Backup complete. Duplicate candidates (read-only unless -Apply):"
foreach ($name in $knownDuplicates) {
    schtasks.exe /query /tn $name 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "  $name" }
}
if (-not $Apply) { Write-Host "Dry run only. Review backup, then rerun with -Apply."; exit 0 }
foreach ($name in $knownDuplicates) {
    schtasks.exe /query /tn $name 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0 -and $PSCmdlet.ShouldProcess($name, "Disable duplicate scheduled task")) {
        schtasks.exe /change /tn $name /disable | Out-Host
    }
}
Write-Host "Duplicates disabled. Roll back with: schtasks.exe /change /tn <name> /enable"
