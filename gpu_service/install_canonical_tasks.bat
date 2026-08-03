@echo off
setlocal
set "BASE=%~dp0"
set "PYTHON=C:\Python313\python.exe"
set "WATCHDOG=%BASE%watchdog_agent.py"
echo This registers only the canonical watchdog task.
echo Run task_audit_and_apply.ps1 -Apply separately after reviewing its backup.
schtasks /create /tn "DouyinGPU-Watchdog" /tr "\"%PYTHON%\" \"%WATCHDOG%\"" /sc onstart /delay 0001:00 /ru neo /rl highest /f
if errorlevel 1 exit /b 1
echo Canonical watchdog task installed. The watchdog owns GPU and ComfyUI startup.
endlocal
