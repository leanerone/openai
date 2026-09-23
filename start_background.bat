@echo off
cd /d "%~dp0"
echo Starting proxy in background...
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process pythonw.exe -ArgumentList 'codex_proxy.py' -WorkingDirectory '%CD%' -WindowStyle Hidden"
timeout /t 2 /nobreak >nul
echo Done. Verify with: status.ps1