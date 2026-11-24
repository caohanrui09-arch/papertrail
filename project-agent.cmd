@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
 ".cache\stage17\runtime\Scripts\python.exe" -E -s -m research77.control start
) else (
 ".cache\stage17\runtime\Scripts\python.exe" -E -s -m research77.control %*
)
exit /b %errorlevel%
