@echo off
setlocal
cd /d "%~dp0"
".cache\stage17\runtime\Scripts\python.exe" -E -s -m scripts.search_v2_polished_control %*
exit /b %errorlevel%
