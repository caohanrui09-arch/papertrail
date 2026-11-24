@echo off
setlocal
cd /d "%~dp0"
"runtime\python\python.exe" -E -s -u "handoff\2026-11-22\preview_server.py" %*
if errorlevel 1 pause
