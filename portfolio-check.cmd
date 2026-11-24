@echo off
setlocal
cd /d "%~dp0"
".cache\stage17\runtime\Scripts\python.exe" -E -s -m scripts.verify_portfolio_delivery --check
exit /b %errorlevel%
