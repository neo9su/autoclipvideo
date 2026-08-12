# Check录像文件结构
Write-Host "=== 录像目录结构 ==="
Get-ChildItem 'C:\Users\neo\douyin_recordings' -Directory | ForEach-Object {
    Write-Host ""
    Write-Host "Room $($_.Name):"
    Get-ChildItem $_.FullName -File | Select-Object Name, Length, LastWriteTime | Sort-Object LastWriteTime -Descending | Select-Object -First 5
}

Write-Host ""
Write-Host "=== 检查特定文件 ==="
$files = @(
    'C:\Users\neo\douyin_recordings\1\1_20260811_002921_000.mp4',
    'C:\Users\neo\douyin_recordings\2\2_20260811_002921_000.mp4',
    'C:\Users\neo\douyin_recordings\1\1_20260811_002634_000.mp4',
    'C:\Users\neo\douyin_recordings\2\2_20260811_002634_000.mp4'
)
foreach ($f in $files) {
    Write-Host "$f : $(Test-Path $f)"
}
