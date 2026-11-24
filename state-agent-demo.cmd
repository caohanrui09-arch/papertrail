@echo off
setlocal
cd /d "%~dp0"
".cache\stage6-env\Scripts\python.exe" -m scripts.constrained_demo
exit /b %errorlevel%
