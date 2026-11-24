@echo off
setlocal
pushd "%~dp0"
if "%~1"=="start" goto start
if "%~1"=="status" goto status
if "%~1"=="stop" goto stop
echo Usage: service.cmd start ^| status ^| stop
popd
exit /b 2
:start
".cache\stage17\runtime\Scripts\python.exe" -E -s -m scripts.local_service_control start
goto done
:status
".cache\stage17\runtime\Scripts\python.exe" -E -s -m scripts.local_service_control status
goto done
:stop
".cache\stage17\runtime\Scripts\python.exe" -E -s -m scripts.local_service_control stop
:done
set "service_exit=%errorlevel%"
popd
exit /b %service_exit%
