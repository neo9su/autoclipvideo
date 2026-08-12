# Quick fix for transcribe.py timezone issue
# Run this on the Windows server: powershell -ExecutionPolicy Bypass -File fix_transcribe_simple.ps1

$transcribePath = "C:\Users\neo\douyin_backend\backend\transcribe.py"

Write-Host "Fixing transcribe.py timezone issue..."
Write-Host "File: $transcribePath"
Write-Host ""

# Backup
$backup = $transcribePath + ".bak." + (Get-Date -Format "yyyyMMdd_HHmmss")
Copy-Item $transcribePath $backup -Force
Write-Host "Backup created: $backup"

# Read content
$content = Get-Content $transcribePath -Raw

# Apply fix
if ($content -match "julianday\('now'\)") {
    $fixed = $content -replace "julianday\('now'\)", "julianday('now', '-8 hours')"
    Set-Content $transcribePath $fixed -NoNewline
    Write-Host "Fix applied: Added '-8 hours' timezone offset" -ForegroundColor Green
} else {
    Write-Host "Pattern not found. Please check the file manually." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Restart backend service:" -ForegroundColor Cyan
Write-Host "  Get-Process | Where-Object {\$_.ProcessName -eq 'python' -and \$_.CommandLine -like '*uvicorn*' -and \$_.CommandLine -like '*main:app*'} | Stop-Process -Force"
Write-Host "  cd C:\Users\neo\douyin_backend\backend"
Write-Host "  C:\Python313\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8899"
Write-Host ""
