@echo off
setlocal
pushd "%~dp0"
if not exist ".cache\stage6-env\Scripts\python.exe" (
  echo Local runtime missing. See docs\REPRODUCIBILITY.md
  popd
  exit /b 2
)
".cache\stage6-env\Scripts\python.exe" -m gsearch.showcase
set "showcase_exit=%errorlevel%"
popd
exit /b %showcase_exit%
