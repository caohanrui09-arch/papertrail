@echo off
setlocal
cd /d "%~dp0"
call unified-service.cmd start
if errorlevel 1 exit /b %errorlevel%
".cache\stage17\runtime\Scripts\python.exe" -E -s -m gsearch.portfolio_demo %*
exit /b %errorlevel%
