@echo off
cd /d "%~dp0"
title Codex Internal API Proxy
if not exist .env (
    echo .env not found! Run: copy .env.example .env
    pause
    exit /b 1
)
echo Starting proxy on http://127.0.0.1:8000 (Ctrl+C to quit)...
python codex_proxy.py
if errorlevel 1 (
    echo Proxy exited with error.
    pause
)