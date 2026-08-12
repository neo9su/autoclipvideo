@echo off
echo === GPU Admin Setup ===
echo.
echo Installing GPU Admin Server as Windows service...
echo.

cd /d C:\Users\neo\douyin_processor

:: Create service
sc.exe create GpuAdmin binPath= "C:\Python313\python.exe -m gpu_admin" start= auto

:: Start service
sc.exe start GpuAdmin

echo.
echo Admin server should be running on port 9999
echo Test: curl http://localhost:9999/health
echo.
pause
