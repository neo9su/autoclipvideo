@echo off
:: Run this once as Administrator to register start_all.bat as a boot-time task.
:: The task runs as user "neo" at system startup (before logon).

set TASKNAME=DouyinGPUServices
set SCRIPT=C:\Users\neo\douyin_processor\start_all.bat

echo Registering Task Scheduler entry: %TASKNAME%

:: Delete old entry if exists
schtasks /delete /tn "%TASKNAME%" /f >nul 2>&1

:: Create new task: runs at system startup as neo, highest privileges
schtasks /create ^
  /tn "%TASKNAME%" ^
  /tr "%SCRIPT%" ^
  /sc onstart ^
  /ru neo ^
  /rl highest ^
  /delay 0001:00 ^
  /f

if %errorlevel%==0 (
    echo.
    echo Task registered successfully.
    echo   Name    : %TASKNAME%
    echo   Trigger : At system startup
    echo   User    : neo
    echo   Script  : %SCRIPT%
    echo.
    echo To verify:  schtasks /query /tn "%TASKNAME%" /fo LIST
    echo To run now: schtasks /run  /tn "%TASKNAME%"
    echo To remove:  schtasks /delete /tn "%TASKNAME%" /f
) else (
    echo.
    echo FAILED to register task. Please run this script as Administrator.
)

pause
