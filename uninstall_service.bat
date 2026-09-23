@echo off
set SERVICE_NAME=CodexInternalProxy
nssm stop "%SERVICE_NAME%" 2>nul
nssm remove "%SERVICE_NAME%" confirm
echo Removed service "%SERVICE_NAME%".
pause