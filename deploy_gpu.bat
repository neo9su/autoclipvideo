@echo off
echo ============================================================
echo GPU Service Startup Script
echo Started at: %date% %time%
echo ============================================================

set LLM_BASE_URL=https://apihub.agnes-ai.com/v1
set LLM_API_KEY=cpk-ErMMhePBGaBFp1y2mr6SmP9GkjHnliCMeM0L1qD39B1FK8Qo

cd /d C:\Users\neo\gpu_service
set STORAGE_DIR=F:\douyin_recordings

echo Starting GPU service on port 8877...
C:\Python313\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8877
