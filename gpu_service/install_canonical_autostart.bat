@echo off
setlocal
:: Canonical boot entrypoint. Run as Administrator once after reviewing paths.
:: Backup existing Task Scheduler definitions before disabling duplicates.
set TASKNAME=DouyinGPUServices
set SCRIPT=C:\Users\neo\douyin_processor\start_all.bat
set BACKUPDIR=C:\Users\neo\douyin_processor\task-backups
if not exist "%BACKUPDIR%" mkdir "%BACKUPDIR%"

for %%T in (GPUService DouyinGPUServices_Boot StartGPUSvc) do (
  schtasks /query /tn "%%T" >nul 2>&1
  if not errorlevel 1 (
    echo Backing up and disabling duplicate task %%T
    schtasks /query /tn "%%T" /xml > "%BACKUPDIR%\%%T.xml"
    schtasks /change /tn "%%T" /disable
  )
)

schtasks /query /tn "%TASKNAME%" >nul 2>&1
if not errorlevel 1 schtasks /query /tn "%TASKNAME%" /xml > "%BACKUPDIR%\%TASKNAME%-before.xml"
schtasks /delete /tn "%TASKNAME%" /f >nul 2>&1
schtasks /create /tn "%TASKNAME%" /tr "\"%SCRIPT%\"" /sc onstart /ru neo /rl highest /delay 0001:00 /f
if errorlevel 1 (
  echo Failed to create canonical task
  exit /b 1
)
echo Canonical task installed: %TASKNAME%
echo Rollback: import XML files from %BACKUPDIR% and re-enable original tasks only after review.
endlocal
