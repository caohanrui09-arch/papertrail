@echo off
setlocal
cd /d "%~dp0"
".cache\stage17\runtime\Scripts\python.exe" -E -s -m scripts.paper_workspace_control %*
exit /b %errorlevel%
