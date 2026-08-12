@echo off
set LLM_BASE_URL=https://apihub.agnes-ai.com/v1
set LLM_API_KEY=cpk-ErMMhePBGaBFp1y2mr6SmP9GkjHnliCMeM0L1qD39B1FK8Qo
set AWS_BEARER_TOKEN_BEDROCK=cpk-ErMMhePBGaBFp1y2mr6SmP9GkjHnliCMeM0L1qD39B1FK8Qo
cd /d C:\Users\neo\douyin_backend\backend
start /B C:\Python313\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8899
timeout /t 5
curl.exe -s http://localhost:8899/api/status
