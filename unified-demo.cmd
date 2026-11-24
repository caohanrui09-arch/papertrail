@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" goto fixed
if "%~1"=="fixed" goto fixed
if "%~1"=="llm_agent" goto llm
echo Usage: unified-demo.cmd fixed ^| llm_agent
exit /b 2
:fixed
".cache\stage6-env\Scripts\python.exe" -m gsearch.unified_agent --policy fixed
exit /b %errorlevel%
:llm
".cache\stage6-env\Scripts\python.exe" -m gsearch.unified_agent --policy llm_agent
exit /b %errorlevel%
