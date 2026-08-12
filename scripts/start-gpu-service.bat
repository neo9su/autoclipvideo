@echo off
REM Startup script for GPU Service
REM Run from C:\Users\neo\douyin_processor\

cd /d C:\Users\neo\douyin_processor
start /MIN python -m gpu_service.main
echo %date% %time% GPU Service started >> C:\Temp\gpu_logs\startup.log
