@echo off
setlocal
cd /d "%~dp0"
".cache\stage17\runtime\Scripts\python.exe" -E -s -m scripts.preference_backup_control %*
exit /b %errorlevel%
