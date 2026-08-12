@echo off
set LLM_BASE_URL=https://apihub.agnes-ai.com/v1
set LLM_API_KEY=cpk-ErMMhePBGaBFp1y2mr6SmP9GkjHnliCMeM0L1qD39B1FK8Qo
cd /d C:\Users\neo\gpu_service
start /B C:\Python313\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8877
timeout /t 5
curl.exe -s http://localhost:8877/health
