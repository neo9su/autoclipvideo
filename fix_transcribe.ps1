# Douyin Recorder - Transcribe Timezone Fix
# This script applies the timezone fix and restarts the backend

$transcribePath = "C:\Users\neo\douyin_backend\backend\transcribe.py"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Douyin Recorder - Transcribe Timezone Fix" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check if file exists
if (-not (Test-Path $transcribePath)) {
    Write-Host "ERROR: transcribe.py not found at $transcribePath" -ForegroundColor Red
    exit 1
}

# Step 1: Find and restore backup
Write-Host "[1/4] Finding backup files..." -ForegroundColor Yellow
$backups = Get-ChildItem "$transcribePath.bak*" -ErrorAction SilentlyContinue | 
           Sort-Object LastWriteTime -Descending
if ($backups) {
    $latestBackup = $backups[0]
    Write-Host "  Found backup: $($latestBackup.Name)" -ForegroundColor Green
    Write-Host "  Restoring from backup..." -ForegroundColor Yellow
    Copy-Item $latestBackup.FullName $transcribePath -Force
    Write-Host "  Backup restored!" -ForegroundColor Green
} else {
    Write-Host "  No backup found, will apply fix directly" -ForegroundColor Yellow
}
Write-Host ""

# Step 2: Apply timezone fix using Python
Write-Host "[2/4] Applying timezone fix..." -ForegroundColor Yellow
$pythonCode = @'
import re
path = r'C:\Users\neo\douyin_backend\backend\transcribe.py'
try:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if fix already applied
    if "julianday('now', '-8 hours')" in content:
        print("Fix already applied, skipping...")
    else:
        # Apply fix
        content = content.replace("julianday('now')", "julianday('now', '-8 hours')")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("Timezone fix applied successfully!")
except Exception as e:
    print(f"Error: {e}")
'@

$pythonOutput = python -c $pythonCode 2>&1
Write-Host "  $pythonOutput" -ForegroundColor Green
Write-Host ""

# Step 3: Verify syntax
Write-Host "[3/4] Verifying Python syntax..." -ForegroundColor Yellow
$syntaxCheck = python -c "import py_compile; py_compile.compile(r'$transcribePath', doraise=True)" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Syntax OK!" -ForegroundColor Green
} else {
    Write-Host "  Syntax Error: $syntaxCheck" -ForegroundColor Red
}
Write-Host ""

# Step 4: Restart backend
Write-Host "[4/4] Restarting backend service..." -ForegroundColor Yellow

# Find and stop existing process
$pythonProcs = Get-Process python -ErrorAction SilentlyContinue | 
               Where-Object { $_.CommandLine -like "*main:app*" -and $_.CommandLine -like "*uvicorn*" }

if ($pythonProcs) {
    Write-Host "  Stopping $($pythonProcs.Count) process(es)..." -ForegroundColor Yellow
    $pythonProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    
    # Verify stopped
    $stillRunning = Get-Process python -ErrorAction SilentlyContinue | 
                    Where-Object { $_.CommandLine -like "*main:app*" }
    if ($stillRunning) {
        Write-Host "  Forcing kill on remaining processes..." -ForegroundColor Red
        $stillRunning | Stop-Process -Force
        Start-Sleep -Seconds 2
    }
} else {
    Write-Host "  No running backend process found" -ForegroundColor Yellow
}

# Start new backend
Write-Host "  Starting new backend..." -ForegroundColor Cyan
$process = Start-Process -FilePath "C:\Python313\python.exe" `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8899" `
    -WorkingDirectory "C:\Users\neo\douyin_backend\backend" `
    -WindowStyle Normal `
    -PassThru

Start-Sleep -Seconds 2
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Fix Applied Successfully!" -ForegroundColor Green
Write-Host "Backend PID: $($process.Id)" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Wait 30 seconds for poll loop to run" -ForegroundColor White
Write-Host "2. Check queue: Invoke-WebRequest http://localhost:8899/api/transcribe-queue" -ForegroundColor White
Write-Host "3. Check recordings: Invoke-WebRequest http://localhost:8899/api/recordings?limit=5&transcribed=0" -ForegroundColor White
Write-Host ""
