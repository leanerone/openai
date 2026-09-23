@echo off
set SERVICE_NAME=CodexInternalProxy
set APP_DIR=%~dp0
where python >nul 2>&1
if errorlevel 1 ( echo Python not found in PATH.& pause& exit /b 1 )
where nssm >nul 2>&1
if errorlevel 1 (
    echo NSSM not found. Download from https://nssm.cc/download and put nssm.exe in PATH.
    echo Skipping service install. Use install_schtask.ps1 instead.
    pause& exit /b 1
)
for /f "delims=" %%p in ('where python') do set PYTHON_PATH=%%p
echo Installing Windows service "%SERVICE_NAME%" using NSSM...
nssm install "%SERVICE_NAME%" "%PYTHON_PATH%" "%APP_DIR%codex_proxy.py"
nssm set "%SERVICE_NAME%" AppDirectory "%APP_DIR%"
nssm set "%SERVICE_NAME%" DisplayName "Codex Internal API Proxy"
nssm set "%SERVICE_NAME%" Description "Proxies Codex CLI/Desktop to internal Chat Completions endpoint"
nssm set "%SERVICE_NAME%" Start SERVICE_AUTO_START
nssm set "%SERVICE_NAME%" AppStdout "%APP_DIR%service-stdout.log"
nssm set "%SERVICE_NAME%" AppStderr "%APP_DIR%service-stderr.log"
nssm set "%SERVICE_NAME%" AppRotateFiles 1
nssm set "%SERVICE_NAME%" AppRotateBytes 10485760
echo.
echo Service installed. To start: nssm start "%SERVICE_NAME%"
pause