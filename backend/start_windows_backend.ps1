param(
    [int]$Port = 8899,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendProcessPattern = "uvicorn main:app.*$Port"

function Get-ActiveSession {
    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name.Split("\\")[-1]
    $lines = @(quser 2>$null)
    foreach ($line in $lines | Select-Object -Skip 1) {
        $fields = ($line -replace "^>\s*", "").Trim() -split "\s+"
        $idIndex = -1
        for ($index = 0; $index -lt [Math]::Min(4, $fields.Count); $index++) {
            if ($fields[$index] -match "^\d+$") { $idIndex = $index; break }
        }
        if ($idIndex -ge 0 -and $fields.Count -gt ($idIndex + 1) -and
            $fields[$idIndex + 1] -match "^(Active|运行中)$" -and
            $fields[0] -ieq $currentUser) {
            return [int]$fields[$idIndex]
        }
    }
    return $null
}

function Get-BackendFromOtherSession {
    param([int]$SessionId)
    $processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'"
    return @($processes | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $backendProcessPattern -and $_.SessionId -ne $SessionId
    })
}

while ($true) {
    $sessionId = Get-ActiveSession
    if ($null -eq $sessionId) {
        Write-Host "No active desktop session for the current user; waiting..."
        Start-Sleep -Seconds 15
        continue
    }

    $conflictingProcesses = Get-BackendFromOtherSession -SessionId $sessionId
    if ($conflictingProcesses.Count -gt 0) {
        Write-Warning "Backend listener conflict detected on port $Port; an existing backend process is active. No process was stopped."
        Start-Sleep -Seconds 15
        continue
    }
    Push-Location $scriptRoot
    try {
        Write-Host "Starting backend in interactive Windows session $sessionId"
        $backend = Start-Process -FilePath $Python `
            -ArgumentList @("-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$Port") `
            -WorkingDirectory $scriptRoot -PassThru
        while (-not $backend.HasExited) {
            Start-Sleep -Seconds 10
            $activeSessionId = Get-ActiveSession
            if ($null -eq $activeSessionId -or $activeSessionId -ne $backend.SessionId) {
                Write-Host "Interactive session changed; restarting backend in the active session"
                Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
                break
            }
            $backend.Refresh()
        }
        if ($backend.ExitCode -ne 0) {
            Write-Warning "Backend exited with code $($backend.ExitCode). Check the startup log for a listener conflict or configuration error; no automatic retry is performed."
            break
        }
    } finally {
        Pop-Location
    }
    Start-Sleep -Seconds 3
}
