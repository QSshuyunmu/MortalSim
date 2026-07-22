@echo off
setlocal
set "PACKAGED=%~dp0dist\MortalSim\MortalSim.exe"
if exist "%PACKAGED%" (
  start "MortalSim" "%PACKAGED%"
  exit /b 0
)
set "PORTABLE=%~dp0MortalSim.exe"
if exist "%PORTABLE%" (
  start "MortalSim" "%PORTABLE%"
  exit /b 0
)
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if exist "%PYTHON%" (
  "%PYTHON%" "%~dp0run_mortalsim.py"
  exit /b %ERRORLEVEL%
)
py -3.13 "%~dp0run_mortalsim.py"
endlocal
