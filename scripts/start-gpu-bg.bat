@echo off
cd /d C:\Users\neo\douyin_processor
start /min C:\Python313\python.exe -m gpu_service.main
timeout /t 3 >nul
echo Started
