@echo off
setlocal
cd /d "%~dp0"
".cache\stage17\runtime\Scripts\python.exe" -E -s -m gsearch.human_quality status
exit /b %errorlevel%
