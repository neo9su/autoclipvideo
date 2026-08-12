@echo off
cd C:\Users\neo\gpu_service
start /B C:\Python313\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8877
echo GPU Service started
