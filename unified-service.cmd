@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="start" goto run
if "%~1"=="status" goto run
if "%~1"=="stop" goto run
echo Usage: unified-service.cmd start ^| status ^| stop
exit /b 2
:run
".cache\stage17\runtime\Scripts\python.exe" -E -s -m scripts.unified_service_control %1
exit /b %errorlevel%
