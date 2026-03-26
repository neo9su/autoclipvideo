@echo off
setlocal

echo --- Stopping Douyin GPU Services ---
echo.

:: Stop via watchdog API first (graceful)
curl -s --max-time 3 http://localhost:8878/health >nul 2>&1
if %errorlevel%==0 (
    echo Stopping gpu service via watchdog...
    curl -s -X POST --max-time 5 http://localhost:8878/stop/gpu >nul 2>&1
    echo Stopping comfyui via watchdog...
    curl -s -X POST --max-time 5 http://localhost:8878/stop/comfyui >nul 2>&1
    timeout /t 2 /nobreak >nul
)

:: Kill watchdog process on port 8878
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8878 "') do (
    echo Killing watchdog (PID %%p)...
    taskkill /PID %%p /F >nul 2>&1
)

:: Kill gpu_service process on port 8877
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8877 "') do (
    echo Killing gpu_service (PID %%p)...
    taskkill /PID %%p /F >nul 2>&1
)

:: Kill ComfyUI process on port 8188
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8188 "') do (
    echo Killing comfyui (PID %%p)...
    taskkill /PID %%p /F >nul 2>&1
)

timeout /t 2 /nobreak >nul

:: Verify
echo.
echo --- Verifying all stopped ---
curl -s --max-time 2 http://localhost:8877/health >nul 2>&1
if %errorlevel%==0 (echo [WARN] gpu_service still responding on :8877) else (echo [OK] gpu_service stopped)

curl -s --max-time 2 http://localhost:8878/health >nul 2>&1
if %errorlevel%==0 (echo [WARN] watchdog still responding on :8878) else (echo [OK] watchdog stopped)

curl -s --max-time 2 http://localhost:8188/system_stats >nul 2>&1
if %errorlevel%==0 (echo [WARN] comfyui still responding on :8188) else (echo [OK] comfyui stopped)

echo.
echo Done.
pause
endlocal
