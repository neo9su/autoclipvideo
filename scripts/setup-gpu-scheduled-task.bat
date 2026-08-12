@echo off
echo === Setting up GPU Service Scheduled Tasks ===
echo.

:: Create health check script
echo Creating C:\Users\neo\douyin_processor\check-gpu.bat...
(
echo @echo off
echo title GPU Health Check
echo cd /d C:\Users\neo\douyin_processor
echo python check_gpu.py
echo if %%ERRORLEVEL%% NEQ 0 (
echo   echo GPU service unhealthy, restarting...
echo   taskkill /F /IM python.exe /FI "IMAGENAME eq python.exe" 2^>nul
echo   timeout /t 3 /nobreak ^>nul
echo   start /min C:\Python313\python.exe -m gpu_service.main
echo )
) > check-gpu.bat

:: Create scheduled task to run every 5 minutes
schtasks /create /tn "GPUHealthMonitor" /tr "cmd /c C:\Users\neo\douyin_processor\check-gpu.bat" /sc minute /mo 5 /rl highest /f
if %%ERRORLEVEL%% EQU 0 (
    echo Created scheduled task: GPUHealthMonitor (every 5 minutes)
)

:: Create startup task
schtasks /create /tn "GPUServiceStart" /tr "cmd /c C:\Users\neo\douyin_processor\start-gpu.bat" /sc onlogon /rl highest /f
if %%ERRORLEVEL%% EQU 0 (
    echo Created scheduled task: GPUServiceStart (on logon)
)

echo.
echo Done!
pause
