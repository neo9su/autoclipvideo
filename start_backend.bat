@echo off
cd C:\Users\neo\douyin_backend\backend
start /B C:\Python313\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8899
echo Backend started
