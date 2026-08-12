@echo off
cd /d C:\Users\neo\douyin_processor
start /B C:\Python313\python.exe -m gpu_service.main
timeout /t 5 >nul
curl -s http://localhost:8877/health
