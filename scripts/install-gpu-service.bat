@echo off
set WORK_DIR=C:\Users\neo\douyin_processor
set PYTHON=C:\Python313\python.exe

echo === GPU Service Installation ===
echo.

:: 检查服务是否已存在
sc.exe query GpuService >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Stopping existing service...
    sc.exe stop GpuService
    sc.exe delete GpuService
    timeout /t 3 /nobreak >nul
)

:: 创建服务
echo Creating Windows service...
sc.exe create GpuService binPath= "%PYTHON% -m gpu_service.main" start= auto DisplayName= "GPU TTS Service"
if %ERRORLEVEL% equ 0 (
    echo Service created successfully!
    echo.
    echo Starting service...
    sc.exe start GpuService
    if %ERRORLEVEL% equ 0 (
        echo.
        echo GPU Service installed and started!
        echo Test: curl http://localhost:8877/health
    ) else (
        echo Failed to start service
    )
) else (
    echo Failed to create service
)
echo.
pause
