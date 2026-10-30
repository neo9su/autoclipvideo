param(
    [int]$Port = 8899,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendProcessPattern = "uvicorn main:app.*$Port"

function Get-ActiveSession {
    # InteractiveToken already places this supervisor in its user's desktop.
    # A disconnected RDP session remains valid and must still recover children.
    $sessionId = (Get-Process -Id $PID).SessionId
    if ($sessionId -gt 0) { return [int]$sessionId }
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

    # Check the socket too: another account's command line may be inaccessible.
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -eq $Port })
    if ($listeners.Count -gt 0) {
        Start-Sleep -Seconds 15
        continue
    }
    $conflictingProcesses = @(Get-BackendFromOtherSession -SessionId $sessionId)
    if ($conflictingProcesses.Count -gt 0) {
        Write-Warning "Backend listener conflict detected on port $Port; an existing backend process is active. No process was stopped."
        Start-Sleep -Seconds 15
        continue
    }
    Push-Location $scriptRoot
    try {
        Write-Host "Starting backend in interactive Windows session $sessionId"
        $backend = Start-Process -FilePath $Python -WindowStyle Hidden `
            -ArgumentList @("-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$Port") `
            -WorkingDirectory $scriptRoot -PassThru
        while (-not $backend.HasExited) {
            # Session discovery must never terminate in-flight backend work.
            Start-Sleep -Seconds 10
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
