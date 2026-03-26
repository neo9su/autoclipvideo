@echo off
setlocal

set WORKDIR=C:\Users\neo\douyin_processor
set PYTHON=C:\Python313\python.exe

cd /d %WORKDIR%

:: Check if watchdog already running
curl -s --max-time 2 http://localhost:8878/health >nul 2>&1
if %errorlevel%==0 (
    echo Watchdog already running on :8878
    goto :status
)

:: Kill any stale process on port 8878
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8878 "') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: Launch watchdog detached from session (no stdio redirect - watchdog writes its own watchdog.log)
echo Starting watchdog_agent on port 8878 ...
powershell -Command "Start-Process -FilePath '%PYTHON%' -ArgumentList 'watchdog_agent.py' -WorkingDirectory '%WORKDIR%' -WindowStyle Hidden"

:: Wait up to 40s for watchdog to respond
set /a TRIES=0
:wait_loop
timeout /t 2 /nobreak >nul
curl -s --max-time 2 http://localhost:8878/health >nul 2>&1
if %errorlevel%==0 goto :watchdog_ok
set /a TRIES+=1
if %TRIES% lss 20 goto :wait_loop
echo WARNING: watchdog did not respond after 40s, check %WORKDIR%\watchdog.log
goto :status

:watchdog_ok
echo Watchdog started OK.

:status
echo.
echo --- GPU service (port 8877) ---
curl -s --max-time 4 http://localhost:8877/health || echo   not ready yet (model loading...)
echo.
echo --- Watchdog (port 8878) ---
curl -s --max-time 4 http://localhost:8878/status || echo   not ready yet
echo.
echo Logs: %WORKDIR%\watchdog.log
echo       %WORKDIR%\gpu_service.log
endlocal
