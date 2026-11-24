@echo off
setlocal
cd /d "%~dp0"
".cache\stage6-env\Scripts\python.exe" -E -s -m scripts.isolated_state_demo %*
exit /b %errorlevel%
