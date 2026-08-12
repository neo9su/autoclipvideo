@echo off
cd /d C:\Users\neo\douyin_backend\backend
C:\Python313\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8899
