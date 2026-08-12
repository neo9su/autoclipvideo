@echo off
echo === GPU Service Auto-Start Setup ===
echo.

:: Create recovery script
echo Recovery script: C:\Users\neo\douyin_processor\recovery-gpu.bat
echo.

:: Create Windows Scheduled Task for periodic health check
schtasks /create /tn "GPUHealthCheck" /tr "cmd /c C:\Users\neo\douyin_processor\check-gpu.bat" /sc minute /mo 5 /rl highest /f

:: Create auto-start task
schtasks /create /tn "GPUServiceStart" /tr "cmd /c C:\Users\neo\douyin_processor\start-gpu.bat" /sc onlogon /rl highest /f

echo Done!
echo Scheduled tasks created:
echo - GPUHealthCheck: Every 5 minutes
echo - GPUServiceStart: On logon
pause
