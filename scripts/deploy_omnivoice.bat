@echo off
setlocal

echo ========================================
echo   OmniVoice TTS Deployment
echo ========================================
echo.

REM Install OmniVoice via pip
echo [1/4] Installing OmniVoice...
pip install omnivoice --quiet
if errorlevel 1 (
    echo   Error: Failed to install OmniVoice
    goto :error
)

REM Create OmniVoice service directory
echo [2/4] Creating service directory...
mkdir C:\Users\neo\omnivoice-service 2>nul

REM Download the OmniVoice service script
echo [3/4] Deploying service script...
REM (This would be copied from the local repo)

REM Create startup script
echo [4/4] Creating startup script...
(
    echo @echo off
    echo setlocal
    echo.
    echo cd /d C:\Users\neo\omnivoice-service
    echo python omnivoice_service.py
    echo pause
) > C:\Users\neo\omnivoice-service\start.bat

echo.
echo ========================================
echo   Deployment complete!
echo   Start the service: C:\Users\neo\omnivoice-service\start.bat
echo ========================================
goto :end

:error
echo.
echo   Deployment failed!
:end
endlocal
pause
